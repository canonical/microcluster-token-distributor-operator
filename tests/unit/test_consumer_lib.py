# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Consumer-side token lifecycle regression tests for LP#2170962."""

import json
from dataclasses import replace
from subprocess import PIPE, CompletedProcess
from unittest.mock import patch

import charms.microcluster_token_distributor.v0.token_distributor as token_lib
import ops
import pytest
from ops import testing

from charm import CONTROL_RELATION, TokenDistributor


class ConsumerCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.consumer = token_lib.TokenConsumer(self, "cluster", ["microovn", "cluster"])


class LegacyMirrorCharm(ops.CharmBase):
    """Implement the legacy wire contract without understanding request IDs."""

    def __init__(self, framework):
        super().__init__(framework)
        self.framework.observe(self.on[CONTROL_RELATION].relation_changed, self._on_changed)

    def _on_changed(self, event):
        mirrored = {}
        for relation in self.model.relations[CONTROL_RELATION]:
            for unit in relation.units:
                data = relation.data[unit]
                if hostname := data.get("hostname"):
                    mirrored.setdefault(f"mirror-{hostname}", "empty")
                if data.get("mirror") == "up":
                    mirrored.update(
                        (key, value)
                        for key, value in data.items()
                        if key.startswith("mirror-") and value != "empty"
                    )
        for relation in self.model.relations[CONTROL_RELATION]:
            data = relation.data[self.unit]
            data["mirror"] = "up"
            for key, value in mirrored.items():
                if key not in data or value != "empty":
                    data[key] = value


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
            hostname, _, request_id = data["hostname"].partition(":")
            assert hostname == "replacement"
            assert "token-request-id" not in data
            assert request_id and request_id not in requests
            requests.add(request_id)

            # Retrying the event must retain the current request, not mint another.
            state = ctx.run(
                ctx.on.relation_changed(state.get_relation(relation.id), remote_unit=0), state
            )
            assert state.get_relation(relation.id).local_unit_data == data
            mirror[f"mirror-replacement:{request_id}"] = "consumed-scoped-token"

    command.assert_not_called()


@pytest.mark.parametrize("cross_app", [False, True])
@pytest.mark.parametrize("legacy_distributor", [False, True])
def test_replaced_hostname_gets_fresh_token(ctx, cross_app, legacy_distributor):
    """Exercise both sides with stale caches and two replacements of one hostname."""
    distributor = testing.Context(
        LegacyMirrorCharm if legacy_distributor else TokenDistributor,
        meta={
            "name": "microcluster-token-distributor",
            "provides": {CONTROL_RELATION: {"interface": "worker-cluster"}},
        },
    )
    stale_data = {
        "mirror": "up",
        "mirror-a-voter": "bootstrap-token",
        "mirror-replacement": "consumed-token",
    }
    issued_tokens = []
    request_ids = []
    members = json.dumps([{"name": "a-voter", "role": "voter", "status": "ONLINE"}])

    def cluster_command(command, **kwargs):
        operation, *args = command[2:]
        if operation == "list":
            return CompletedProcess(command, 0, stdout=members, stderr="")
        if operation == "add":
            assert args == ["replacement"]  # The token must match the real hostname.
            token = f"fresh-token-{len(issued_tokens)}"
            issued_tokens.append(token)
            return CompletedProcess(command, 0, stdout=token + "\n", stderr="")
        assert operation == "join"
        assert issued_tokens, "A replacement must request a fresh token before joining"
        assert args == [issued_tokens[-1]]
        return CompletedProcess(command, 0, stdout="", stderr="")

    with patch.object(token_lib.subprocess, "run", side_effect=cluster_command) as run:
        for _ in range(2):
            # A new unit initially sees the previous incarnation's cached token.
            joining_relation = testing.Relation(
                "cluster", remote_app_name="distributor", remote_units_data={0: stale_data}
            )
            joining_state = ctx.run(
                ctx.on.relation_changed(joining_relation, remote_unit=0),
                testing.State(relations=[joining_relation]),
            )
            run.assert_not_called()
            request_data = joining_state.get_relation(joining_relation.id).local_unit_data
            request_id = request_data["hostname"].partition(":")[2]
            assert request_id
            assert "token-request-id" not in request_data
            assert request_id not in request_ids
            request_ids.append(request_id)
            key = f"mirror-{request_data['hostname']}"

            # Keep stale tokens on both the distributor and the communicator.
            provider_relation = testing.Relation(
                CONTROL_RELATION,
                remote_app_name="microovn",
                remote_units_data=(
                    {0: stale_data, 1: request_data} if not cross_app else {0: stale_data}
                ),
                local_unit_data=stale_data,
            )
            relations = [provider_relation]
            target_relation = provider_relation
            if cross_app:
                target_relation = testing.Relation(
                    CONTROL_RELATION,
                    remote_app_name="other-microovn",
                    remote_units_data={0: request_data},
                )
                relations.append(target_relation)
            provider_state = distributor.run(
                distributor.on.relation_changed(
                    target_relation, remote_unit=0 if cross_app else 1
                ),
                testing.State(leader=True, relations=relations),
            )
            mirrored = provider_state.get_relation(provider_relation.id).local_unit_data
            assert mirrored[key] == token_lib.EMPTY_STRING

            # The elected communicator creates a token once for this request.
            communicator_relation = testing.Relation(
                "cluster", remote_units_data={0: mirrored}, local_unit_data=stale_data
            )
            with (
                patch.object(token_lib, "get_hostname", return_value="a-voter"),
                ctx(
                    ctx.on.relation_changed(communicator_relation, remote_unit=0),
                    testing.State(
                        relations=[communicator_relation], unit_status=testing.ActiveStatus()
                    ),
                ) as manager,
            ):
                manager.charm.consumer._stored.in_cluster = True
                communicator_state = manager.run()
            generated = communicator_state.get_relation(communicator_relation.id).local_unit_data
            assert generated[key] == issued_tokens[-1]

            # A repeated event must not mint another token before mirroring catches up.
            token_count = len(issued_tokens)
            with patch.object(token_lib, "get_hostname", return_value="a-voter"):
                ctx.run(
                    ctx.on.relation_changed(
                        communicator_state.get_relation(communicator_relation.id), remote_unit=0
                    ),
                    communicator_state,
                )
            assert len(issued_tokens) == token_count

            provider_relation = replace(
                provider_state.get_relation(provider_relation.id),
                remote_units_data={
                    **provider_relation.remote_units_data,
                    0: generated,
                },
            )
            provider_state = distributor.run(
                distributor.on.relation_changed(provider_relation, remote_unit=0),
                replace(
                    provider_state,
                    relations=[
                        provider_relation if rel.id == provider_relation.id else rel
                        for rel in provider_state.relations
                    ],
                ),
            )
            mirrored = provider_state.get_relation(target_relation.id).local_unit_data
            assert mirrored[key] == issued_tokens[-1]
            joining_relation = replace(
                joining_state.get_relation(joining_relation.id), remote_units_data={0: mirrored}
            )
            joined = ctx.run(
                ctx.on.relation_changed(joining_relation, remote_unit=0),
                replace(joining_state, relations=[joining_relation]),
            )
            assert joined.unit_status == testing.ActiveStatus("Joined cluster")
            # Removal/reprovisioning clears unit state, but leaves both mirrors stale.
            stale_data = mirrored
            run.reset_mock()

    assert len(set(issued_tokens)) == 2


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
    request = state.get_relation(relation.id).local_unit_data["hostname"]
    relation = replace(
        state.get_relation(relation.id),
        remote_units_data={
            0: {
                "mirror": "up",
                "mirror-replacement": "consumed-legacy-token",
                "mirror-replacement:old-request": "consumed-scoped-token",
                f"mirror-{request}": "fresh-token",
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
        assert data["hostname"].startswith("replacement:")
        assert "token-request-id" not in data
        handle_mirror.assert_not_called()


def test_upgrade_advertises_request_once(ctx):
    relation = testing.Relation("cluster", local_unit_data={"hostname": "replacement"})
    state = ctx.run(ctx.on.upgrade_charm(), testing.State(relations=[relation]))
    request_data = state.get_relation(relation.id).local_unit_data
    assert request_data["hostname"].startswith("replacement:")

    state = ctx.run(ctx.on.upgrade_charm(), state)
    assert state.get_relation(relation.id).local_unit_data == request_data


@pytest.mark.parametrize("in_cluster", [False, True])
def test_upgrade_preserves_existing_request_id(ctx, in_cluster):
    relation = testing.Relation(
        "cluster",
        local_unit_data={"hostname": "replacement", "token-request-id": "existing-request"},
    )
    with (
        patch.object(token_lib.TokenConsumer, "_handle_mirror"),
        ctx(ctx.on.upgrade_charm(), testing.State(relations=[relation])) as manager,
    ):
        manager.charm.consumer._stored.in_cluster = in_cluster
        manager.charm.consumer._stored.token_request_id = "existing-request"
        state = manager.run()
    assert state.get_relation(relation.id).local_unit_data == {
        "hostname": "replacement:existing-request"
    }


def test_bootstrap_with_scoped_request(ctx):
    relation = testing.Relation(
        "cluster",
        remote_app_data={"bootstrap-app": "microovn"},
        remote_units_data={0: {"mirror": "up"}},
    )
    with patch.object(token_lib.TokenConsumer, "_call_cluster_command") as command:
        command.side_effect = lambda operation, *args: (
            (0, "") if operation == "bootstrap" else (0, "[]")
        )
        state = ctx.run(
            ctx.on.relation_joined(relation, remote_unit=0),
            testing.State(leader=True, relations=[relation]),
        )

    assert state.unit_status == testing.ActiveStatus("Cluster bootstrapped")
    assert state.get_relation(relation.id).local_unit_data["hostname"].startswith("replacement:")
    command.assert_any_call("bootstrap")


def test_remove_uses_real_hostname(ctx):
    with (
        patch.object(
            token_lib.TokenConsumer, "_call_cluster_command", return_value=(0, "")
        ) as command,
        ctx(ctx.on.remove(), testing.State()) as manager,
    ):
        manager.charm.consumer._stored.in_cluster = True
        manager.charm.consumer._stored.token_request_id = "request-id"
        manager.run()

    command.assert_called_once_with("remove", "replacement")


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
