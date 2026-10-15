# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Consumer-side token lifecycle regression tests for LP#2170962."""

from dataclasses import replace
from subprocess import PIPE, CompletedProcess
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


@pytest.mark.parametrize(
    "args",
    [
        ("join", "private-join-token"),
        ("add", "replacement"),
        ("remove", "replacement"),
        ("list", "-f", "json"),
        ("bootstrap",),
    ],
)
@pytest.mark.parametrize("returncode", [0, 1])
def test_command_diagnostics_exclude_tokens(ctx, caplog, args, returncode):
    stderr = "Join rejected: private-join-token" if args[0] == "join" else "Cluster unavailable"
    with (
        patch.object(token_lib.subprocess, "run") as command,
        ctx(ctx.on.start(), testing.State()) as manager,
    ):
        command.return_value = CompletedProcess(
            [], returncode, stdout="private-output-token", stderr=stderr
        )
        assert manager.charm.consumer._call_cluster_command(*args) == (
            returncode,
            "private-output-token",
        )
    command.assert_called_once_with(
        ["microovn", "cluster", *args], stdout=PIPE, stderr=PIPE, text=True
    )
    if returncode:
        assert f"microovn cluster {args[0]} failed with exit code 1" in caplog.text
        assert ("Join rejected: <redacted>" if args[0] == "join" else stderr) in caplog.text
    else:
        assert stderr not in caplog.text
    assert "private-join-token" not in caplog.text
    assert "private-output-token" not in caplog.text


def test_join_failure_is_blocked_and_deferred_without_logging_token(ctx, caplog):
    token = "private-join-token"
    relation = testing.Relation(
        "cluster",
        remote_units_data={0: {"mirror": "up", "mirror-replacement:request-id": token}},
    )
    with (
        patch.object(token_lib.subprocess, "run") as command,
        ctx(
            ctx.on.relation_changed(relation, remote_unit=0), testing.State(relations=[relation])
        ) as manager,
    ):
        command.return_value = CompletedProcess(
            [], 1, stdout="", stderr=f"Token rejected: {token}"
        )
        manager.charm.consumer._stored.token_request_id = "request-id"
        state = manager.run()
    assert state.unit_status == testing.BlockedStatus("Joining cluster failed")
    assert state.deferred
    assert "Token rejected: <redacted>" in caplog.text
    assert "Failed joining replacement to cluster" in caplog.text
    assert token not in caplog.text


def test_generation_failure_does_not_publish_or_log_stdout(ctx, caplog):
    key = "mirror-replacement:request-id"
    relation = testing.Relation(
        "cluster", remote_units_data={0: {"mirror": "up", key: token_lib.EMPTY_STRING}}
    )
    with (
        patch.object(token_lib.subprocess, "run") as command,
        ctx(ctx.on.start(), testing.State(relations=[relation])) as manager,
    ):
        command.return_value = CompletedProcess([], 1, stdout="private-output-token", stderr="")
        cluster = manager.charm.model.get_relation("cluster")
        assert cluster is not None
        assert not manager.charm.consumer._update_tokens(cluster)
        assert key not in cluster.data[manager.charm.unit]
    assert "exit code 1: No stderr output" in caplog.text
    assert "private-output-token" not in caplog.text
