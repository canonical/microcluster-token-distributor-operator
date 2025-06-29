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
from charms.microcluster_token_distributor.v0.token_distributor import TokenDistributorProvides

logger = logging.getLogger(__name__)
CONTROL_RELATION = "microcluster-cluster"
MIRROR_PREFIX = "mirror-"


class TokenDistributor(ops.CharmBase):
    """Token Distributor Charmed Operator."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        self.token_distributor = TokenDistributorProvides(
            charm=self, relation_name=CONTROL_RELATION
        )

    def _on_start(self, _: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":
    ops.main(TokenDistributor)  # pragma: nocover
