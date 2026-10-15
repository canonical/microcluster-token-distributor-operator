# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Consumer-side token lifecycle regression tests for LP#2170962."""

from dataclasses import replace
from subprocess import CompletedProcess
from unittest.mock import patch

import charms.microcluster_token_distributor.v0.token_distributor as token_lib
import ops
import pytest
from ops import testing


class ConsumerCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.consumer = token_lib.TokenConsumer(self, "cluster", ["microovn", "cluster"])


@pytest.fixture()
def ctx():
    with patch.object(token_lib, "get_hostname", return_value="replacement"):
        yield testing.Context(
            ConsumerCharm,
            meta={"name": "microovn", "requires": {"cluster": {"interface": "worker-cluster"}}},
        )


def test_replacements_ignore_cached_tokens(ctx):
    mirror = {"mirror": "up", "mirror-replacement": "consumed-legacy-token"}
    requests = set()
    with patch.object(token_lib.subprocess, "run") as command:
        for _ in range(2):
            relation = testing.Relation("cluster", remote_units_data={0: mirror})
            state = ctx.run(
                ctx.on.relation_changed(relation, remote_unit=0),
                testing.State(relations=[relation]),
            )
            data = state.get_relation(relation.id).local_unit_data
            request_id = data["token-request-id"]
            assert request_id and request_id not in requests
            requests.add(request_id)

            # Retrying the event must retain the current request, not mint another.
            state = ctx.run(
                ctx.on.relation_changed(state.get_relation(relation.id), remote_unit=0), state
            )
            assert state.get_relation(relation.id).local_unit_data == data
            mirror[f"mirror-replacement:{request_id}"] = "consumed-scoped-token"

    command.assert_not_called()


@pytest.mark.parametrize("key", ["replacement", "replacement:new-request"])
def test_generate_token_for_real_hostname_once(ctx, key):
    mirror_key = f"mirror-{key}"
    relation = testing.Relation(
        "cluster",
        local_unit_data={"mirror-replacement:old-request": "consumed-token"},
        remote_units_data={0: {"mirror": "up", mirror_key: token_lib.EMPTY_STRING}},
    )
    with (
        patch.object(token_lib.subprocess, "run") as command,
        ctx(ctx.on.start(), testing.State(relations=[relation])) as manager,
    ):
        command.return_value = CompletedProcess([], 0, stdout="fresh-token\n", stderr="")
        cluster = manager.charm.model.get_relation("cluster")
        assert cluster is not None
        assert manager.charm.consumer._update_tokens(cluster)
        assert not manager.charm.consumer._update_tokens(cluster)
        assert cluster.data[manager.charm.unit][mirror_key] == "fresh-token"

    assert command.call_count == 1
    assert command.call_args.args[0] == ["microovn", "cluster", "add", "replacement"]


def test_join_uses_token_for_current_request(ctx):
    relation = testing.Relation("cluster")
    state = ctx.run(ctx.on.upgrade_charm(), testing.State(relations=[relation]))
    request_id = state.get_relation(relation.id).local_unit_data["token-request-id"]
    relation = replace(
        state.get_relation(relation.id),
        remote_units_data={
            0: {
                "mirror": "up",
                "mirror-replacement": "consumed-legacy-token",
                "mirror-replacement:old-request": "consumed-scoped-token",
                f"mirror-replacement:{request_id}": "fresh-token",
            }
        },
    )
    with patch.object(token_lib.subprocess, "run") as command:
        command.return_value = CompletedProcess([], 0, stdout="[]", stderr="")
        state = ctx.run(
            ctx.on.relation_changed(relation, remote_unit=0),
            replace(state, relations=[relation]),
        )
    assert state.unit_status == testing.ActiveStatus("Joined cluster")
    assert command.call_args_list[0].args[0] == ["microovn", "cluster", "join", "fresh-token"]


@pytest.mark.parametrize("in_cluster", [False, True])
def test_upgrade_advertises_request_only_for_unjoined_legacy_unit(ctx, in_cluster):
    relation = testing.Relation("cluster", local_unit_data={"hostname": "replacement"})
    with (
        patch.object(token_lib.TokenConsumer, "_handle_mirror") as handle_mirror,
        ctx(ctx.on.upgrade_charm(), testing.State(relations=[relation])) as manager,
    ):
        manager.charm.consumer._stored.in_cluster = in_cluster
        state = manager.run()
    data = state.get_relation(relation.id).local_unit_data
    if in_cluster:
        assert data == relation.local_unit_data
        handle_mirror.assert_called_once()
    else:
        assert data["token-request-id"]
        handle_mirror.assert_not_called()


@pytest.mark.parametrize("local_token", [None, "unmirrored-token"])
def test_handover_with_pending_request(ctx, local_token):
    key = "mirror-replacement:new-request"
    data = {"mirror": "up"}
    if local_token:
        data[key] = local_token
    relation = testing.Relation(
        "cluster",
        local_unit_data=data,
        remote_units_data={0: {"mirror": "up", key: token_lib.EMPTY_STRING}},
    )
    with ctx(ctx.on.start(), testing.State(relations=[relation])) as manager:
        cluster = manager.charm.model.get_relation("cluster")
        assert cluster is not None
        manager.charm.consumer._safely_down_mirror(cluster)
        assert cluster.data[manager.charm.unit]["mirror"] == ("up" if local_token else "down")
