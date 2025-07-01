"""Microcluster token distributor library.

This is a library for the microcluster-token-distributor operator charm and
charms that aim to integrate with it. It allows for distribution generation and
usage of tokens using the token distributor units as a sort of mirror for key
data that the units of the actual microcluster charm expose allowing
communication without the usage of the peer relation.
"""

import json
import logging
import os
import subprocess
import time

import ops

# The unique Charmhub library identifier, never change it
LIBID = "ec674038842544928b4e21ee6e199666"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


logger = logging.getLogger(__name__)

MIRROR_PREFIX = "mirror-"


def mirror_id(hostname):
    """Return the mirror id for the specified hostname.

    :return: the mirror id for the specified hostname
    """
    return "{0}{1}".format(MIRROR_PREFIX, hostname)


def get_hostname():
    """Return the hostname."""
    return os.uname().nodename


class TokenDistributorProvides(ops.framework.Object):
    """Token Distributor Provider class.

    The provides side of the token distributor library.
    It exposes the hostnames found in the connected cluster and copies any data
    put up to be mirrored (typically tokens) in the leader units mirror for
    consumption by units in the connected cluster.
    """

    def __init__(
        self,
        charm: ops.CharmBase,
        relation_name: str,
    ):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name

        self.framework.observe(self.charm.on.leader_elected, self._on_leader_elected)
        self.framework.observe(
            self.charm.on[self.relation_name].relation_changed, self._on_token_relation_changed
        )

    def __handle_mirror(self, relation):
        relation_data = relation.data
        relation_data[self.charm.unit]["mirror"] = "up"
        for unit in relation.units:
            if relation_data[unit].get("mirror") == "up":
                # add all tokens in the other side of the mirror to this side
                for k, v in relation_data[unit].items():
                    if MIRROR_PREFIX in k:
                        relation_data[self.charm.unit][k] = v

            if "hostname" not in relation_data[unit]:
                continue
            mirror_key = mirror_id(relation_data[unit]["hostname"])
            if mirror_key not in relation_data[self.charm.unit]:
                logger.info("added {0} to mirror".format(mirror_key))
                relation_data[self.charm.unit][mirror_key] = "empty"

    def _on_token_relation_changed(self, event: ops.RelationChangedEvent):
        if self.charm.unit.is_leader():
            self.__handle_mirror(event.relation)

    def _on_leader_elected(self, _: ops.RelationChangedEvent):
        if relation := self.charm.model.get_relation(self.relation_name):
            if self.charm.unit.is_leader():
                relation.data[self.charm.unit]["mirror"] = "up"
                self.__handle_mirror(relation)
            elif relation.data[self.charm.unit].get("mirror"):
                relation.data[self.charm.unit]["mirror"] = "down"


class TokenConsumer(ops.framework.Object):
    """Token Consumer class.

    This uses the token distributor relation as a mirror to get information about
    the cluster such as hostnames that need tokens generated. It then generates
    neccicary tokens, which are then consumed by the respective units
    allowing easy cluster management.
    """

    def _call_cluster_command(self, *args):
        result = subprocess.run(
            self.command_name + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.returncode, result.stdout

    def __init__(self, charm: ops.CharmBase, relation_name: str, command_name: str):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.command_name = command_name
        self.relation_name = relation_name
        self.charm._stored.set_default(in_cluster=False)

        self.framework.observe(self.charm.on.install, self._on_install)
        self.framework.observe(self.charm.on.remove, self._on_remove)
        self.framework.observe(
            self.charm.on[self.relation_name].relation_changed, self._on_cluster_changed
        )
        self.framework.observe(
            self.charm.on[self.relation_name].relation_created, self._handle_relation_created
        )

    def _wait_for_pending(self):
        previous_status = self.charm.unit.status
        self.charm.unit.status = ops.WaitingStatus("Waiting on pending nodes")
        pending_nodes = True
        while pending_nodes:
            pending_nodes = False
            error, output = self._call_cluster_command("list", "-f", "json")
            if error:
                logger.error(
                    "{0} calling cluster list failed with code {1}".format(get_hostname(), error)
                )
                return False
            json_output = json.loads(output)
            for x in json_output:
                if x["role"] == "PENDING":
                    pending_nodes = True
                    time.sleep(1)
                    break
        self.charm.unit.status = previous_status
        return True

    def _handle_mirror(self, relation):
        self._update_mirror_state(relation.data)
        if self.__is_communicator_node():
            return self._update_tokens(relation)

    def __is_communicator_node(self):
        # needs to be in cluster and the pending wait must succeed
        if not self.charm._stored.in_cluster or not self._wait_for_pending():
            return False
        error, output = self._call_cluster_command("list", "-f", "json")
        if error:
            logger.error(
                "{0} calling cluster list failed with code {1}".format(get_hostname(), error)
            )
            return False
        json_output = json.loads(output)
        # get nodenames for online voters
        voter_names = [
            x["name"] for x in json_output if (x["role"] in "voter") and (x["status"] == "ONLINE")
        ]
        # return True if there are names and its the lowest name
        return (len(voter_names) > 0) and (get_hostname() == min(voter_names))

    def _update_mirror_state(self, relation_data):
        logger.info("updating mirror status")
        if self.__is_communicator_node():
            relation_data[self.charm.unit]["mirror"] = "up"
        elif relation_data[self.charm.unit].get("mirror"):
            relation_data[self.charm.unit]["mirror"] = "down"

    def _update_tokens(self, relation):
        relation_data = relation.data
        distributor_mirrors = [
            unit
            for unit in relation.units
            if (mirror := relation_data[unit].get("mirror")) and mirror == "up"
        ]

        if len(distributor_mirrors) != 1:
            return False

        distributor_mirror = relation_data[distributor_mirrors[0]]
        new_token = False

        # found token distributor leader
        for mirror_key in distributor_mirror.keys():
            if not mirror_key.startswith(MIRROR_PREFIX):
                continue

            hostname = mirror_key[len(MIRROR_PREFIX) :]

            # skip if token generated
            if (
                distributor_mirror[mirror_key] != "empty"
                or mirror_key in relation_data[self.charm.unit]
            ):
                continue

            # generate token and add to this side of mirror
            error, token = self._call_cluster_command("add", hostname)
            if not error:
                token = token.strip()
                relation_data[self.charm.unit][mirror_key] = token
                logger.info("added token for {}".format(hostname))
                new_token = True

        return new_token

    def _join_with_token(self, token):
        self.charm.unit.status = ops.MaintenanceStatus("Joining cluster")
        error, _ = self._call_cluster_command("join", token)
        if error:
            return False
        self.charm._stored.in_cluster = True
        self.charm.unit.status = ops.ActiveStatus("Joined cluster")
        return True

    def _add_hostname(self, relation):
        relation.data[self.charm.unit]["hostname"] = get_hostname()

    def _find_token(self, relation):
        tokens = [
            token
            for unit in relation.units
            if (token := relation.data[unit].get(mirror_id(get_hostname()))) and token != "empty"
        ]
        if len(tokens) > 1:
            self.charm.unit.status = ops.MaintenanceStatus("Too many tokens")
            return False
        if len(tokens) == 0:
            self.charm.unit.status = ops.MaintenanceStatus("No token yet")
            return False

        logger.info("found token")
        return tokens[0]

    def _any_token_exists(self, relation):
        for unit in relation.units:
            for k in relation.data[unit].keys():
                if k.startswith(MIRROR_PREFIX) and relation.data[unit][k] != "empty":
                    return True
        return False

    def _on_install(self, event: ops.InstallEvent):
        if not self.charm.model.get_relation(self.relation_name):
            self.charm.unit.status = ops.MaintenanceStatus("Waiting for token distrbutor relation")

    def _on_remove(self, event: ops.RemoveEvent):
        if self.charm._stored.in_cluster:
            error, _ = self._call_cluster_command("remove", get_hostname())
            if error:
                logger.error("failed removing {0} from cluster".format(get_hostname()))

    def _on_cluster_changed(self, event: ops.RelationChangedEvent):
        if not self.charm._stored.in_cluster:
            if token := self._find_token(event.relation):
                successful = self._join_with_token(token)
                if not successful:
                    self.charm.unit.status = ops.BlockedStatus("Joining cluster failed")
                    logger.error(
                        "failed {0} joining cluster with token: {1}".format(get_hostname(), token)
                    )
                    event.defer()
                    return

        if self.charm._stored.in_cluster:
            self._handle_mirror(event.relation)

    def _handle_relation_created(self, event: ops.RelationCreatedEvent):
        self._add_hostname(event.relation)
        token_in_cluster = self._any_token_exists(event.relation)

        if (
            not self.charm._stored.in_cluster
            and self.charm.unit.is_leader()
            and not token_in_cluster
        ):
            error, _ = self._call_cluster_command("bootstrap")
            if error:
                logger.error("{0} unable to bootstrap cluster".format(get_hostname()))
                self.charm.unit.status = ops.BlockedStatus("Unable to bootstrap cluster")
                event.defer()
                return
            self.charm._stored.in_cluster = True
            self.charm.unit.status = ops.ActiveStatus("Cluster bootstrapped")
            self._handle_mirror(event.relation)
