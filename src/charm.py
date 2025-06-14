#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Microcluster Token Distributor Charm.

This charm provides token distribution logic for distributing
tokens across a service using the microcluster clustering APIs.
"""

import logging

import ops

logger = logging.getLogger(__name__)
CONTROL_RELATION = "microcluster-cluster"
MIRROR_PREFIX = "mirror-"


def mirror_id(hostname):
    """Return the mirror id for the specified hostname.

    :return: the mirror id for the specified hostname
    """
    return "{0}{1}".format(MIRROR_PREFIX, hostname)


class TokenDistributor(ops.CharmBase):
    """Token Distributor Charmed Operator."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.leader_elected, self._on_leader_elected)
        framework.observe(self.on[CONTROL_RELATION].relation_changed, self._on_peers_changed)

    def _handle_mirror(self, relation):
        relation_data = relation.data
        relation_data[self.unit]["mirror"] = "up"
        for unit in relation.units:
            if relation_data[unit].get("mirror") == "up":
                # add all tokens in the other side of the mirror to this side
                for k, v in relation_data[unit].items():
                    if MIRROR_PREFIX in k:
                        relation_data[self.unit][k] = v

            if "hostname" not in relation_data[unit]:
                continue
            mirror_key = mirror_id(relation_data[unit]["hostname"])
            if mirror_key not in relation_data[self.unit]:
                logger.info("added {0} to mirror".format(mirror_key))
                relation_data[self.unit][mirror_key] = "empty"

    def _on_start(self, _: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    def _on_peers_changed(self, event: ops.RelationChangedEvent):
        if self.unit.is_leader():
            self._handle_mirror(event.relation)

    def _on_leader_elected(self, _: ops.RelationChangedEvent):
        if relation := self.model.get_relation(CONTROL_RELATION):
            if self.unit.is_leader():
                relation.data[self.unit]["mirror"] = "up"
                self._handle_mirror(relation)
            elif relation.data[self.unit].get("mirror"):
                relation.data[self.unit]["mirror"] = "down"


if __name__ == "__main__":
    ops.main(TokenDistributor)  # pragma: nocover
