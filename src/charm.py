#!/usr/bin/env python3
import logging, ops
logger = logging.getLogger(__name__)
CONTROL_RELATION = "microcluster-cluster"
MIRROR_PREFIX = "mirror-"

def mirror_id(hostname):
    return "{0}{1}".format(MIRROR_PREFIX,hostname)

class TokenDistributor(ops.CharmBase):
    def handle_mirror(self, relation):
        relation_data = relation.data
        relation_data[self.unit]["mirror"]="up"
        for unit in relation.units:
            if relation_data[unit].get("mirror") == "up":
                # add all tokens in the other side of the mirror to this side
                for k, v in relation_data[unit].items():
                    if MIRROR_PREFIX in k: relation_data[self.unit][k] = v

            if not "hostname" in relation_data[unit]:
                continue
            mirror_key = mirror_id(relation_data[unit]["hostname"])
            if not mirror_key in relation_data[self.unit]:
                logger.info("added {0} to mirror".format(mirror_key))
                relation_data[self.unit][mirror_key] = "empty"

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.leader_elected , self._on_leader_elected)
        framework.observe(self.on[CONTROL_RELATION].relation_changed,
                            self._on_peers_changed)

    def _on_start(self, _: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    def _on_peers_changed(self, event: ops.RelationChangedEvent):
        if self.unit.is_leader():
            self.handle_mirror(event.relation)

    def _on_leader_elected(self, _: ops.RelationChangedEvent):
        if (relation := self.model.get_relation(CONTROL_RELATION)):
            if self.unit.is_leader():
                relation.data[self.unit]["mirror"]="up"
                self.handle_mirror(relation)
            elif relation.data[self.unit].get("mirror"):
                relation.data[self.unit]["mirror"]="down"

if __name__ == "__main__":
    ops.main(TokenDistributor) # pragma: nocover
