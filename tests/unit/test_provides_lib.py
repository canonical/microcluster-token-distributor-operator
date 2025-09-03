#!/usr/bin/env python3

from unittest.mock import call, patch

import charms.microcluster_token_distributor.v0.token_distributor as token_lib
import pytest
from ops import testing

import charm


def test_handle_mirror_bring_up_self():
    ctx = testing.Context(charm.TokenDistributor)
    cluster_relation = testing.Relation(charm.CONTROL_RELATION, "worker-cluster")
    with ctx(ctx.on.start(), testing.State(relations=[cluster_relation])) as manager:
        cluster_relation = manager.charm.model.get_relation(charm.CONTROL_RELATION)
        # ensure mirror is down before, and then up after
        assert "mirror" not in cluster_relation.data[manager.charm.unit]
        manager.charm.token_distributor._handle_mirror(cluster_relation)
        assert cluster_relation.data[manager.charm.unit]["mirror"] == "up"


def test_handle_mirror_presented_unit_data():
    ctx = testing.Context(charm.TokenDistributor)
    cluster_relation = testing.Relation(
        charm.CONTROL_RELATION,
        "worker-cluster",
        remote_units_data={
            0: {
                "suits": "hearts, diamonds, spades, clubs",
                "mirror-highcards": "ace, king, queen, jack",
                "mirror": "up",
            },
            1: {"mirror-data": "413", "data": "612", "mirror": "up"},
            2: {"mirror_123": "abc", "mirror-abc": "123", "mirror": "up"},
            3: {"mirror": "up", "beverage": "coffee"},
            4: {"mirror-": "sus", "mirror": "up"},
            5: {"mirror-feferi": "meenah"},
            6: {"mirror-superman": "krypton", "mirror": "down"},
        },
    )
    with ctx(ctx.on.start(), testing.State(relations=[cluster_relation])) as manager:
        cluster_relation = manager.charm.model.get_relation(charm.CONTROL_RELATION)
        assert list(cluster_relation.data[manager.charm.unit].keys()) == [
            "egress-subnets",
            "ingress-address",
            "private-address",
        ]
        manager.charm.token_distributor._handle_mirror(cluster_relation)
        unit_databag = cluster_relation.data[manager.charm.unit]

        # dont mirror without mirror prefix in key
        assert "suits" not in unit_databag
        assert "mirror-suits" not in unit_databag
        assert "hearts, diamonds, spades, clubs" not in unit_databag.values()

        # has mirror prefix and mirror is up
        assert "mirror-highcards" in unit_databag
        assert unit_databag["mirror-highcards"] == "ace, king, queen, jack"

        # ensure we use value in mirror-data instead of data on remote unit
        assert "mirror-data" in unit_databag
        assert unit_databag["mirror-data"] == "413"
        assert "data" not in unit_databag
        assert "612" not in unit_databag.values()

        # mirror_ is not the valid mirror prefix
        assert "mirror_123" not in unit_databag
        assert "mirror-123" not in unit_databag
        assert "abc" not in unit_databag.values()

        # mirror- is the valid mirror prefix
        assert "mirror-abc" in unit_databag
        assert unit_databag["mirror-abc"] == "123"

        # dont copy unprefixed data even with mirror up
        assert "beverage" not in unit_databag
        assert "mirror-beverage" not in unit_databag
        assert "coffee" not in unit_databag.values()

        # the prefix alone works as a valid key and therefore is copied
        assert "mirror-" in unit_databag
        assert unit_databag["mirror-"] == "sus"

        # despite prefix being correct, mirror is not up, so not copied
        assert "mirror-feferi" not in unit_databag
        assert "meenah" not in unit_databag.values()

        # despite prefix being correct, mirror is down, so not copied
        assert "mirror-superman" not in unit_databag
        assert "krypton" not in unit_databag.values()


@patch.object(token_lib.logger, "info")
def test_handle_mirror_mirror_hostnames(logger_info):
    ctx = testing.Context(charm.TokenDistributor)
    cluster_relation = testing.Relation(
        charm.CONTROL_RELATION,
        "worker-cluster",
        remote_units_data={
            0: {"hostname": "karkat"},
            1: {"hostname": "terezi", "mirror": "up"},
            2: {"hostname": "gamzee", "mirror": "down"},
            3: {"hostname": "eridan"},
            4: {"host-name": "equius"},
            5: {"nodename": "tavros"},
            6: {"otherdata": "according to all known laws of aviation", "hostname": "sollux"},
            7: {"hostname": "zapano"},
        },
        local_unit_data={
            "mirror-eridan": "example-token-xyz-123",
            "mirror-kanaya": "egbert-lalonde-strider-harley",
            "mirror-zapano": "empty",
        },
    )
    with ctx(ctx.on.start(), testing.State(relations=[cluster_relation])) as manager:
        cluster_relation = manager.charm.model.get_relation(charm.CONTROL_RELATION)
        assert list(cluster_relation.data[manager.charm.unit].keys()) == [
            "mirror-eridan",
            "mirror-kanaya",
            "mirror-zapano",
        ]
        manager.charm.token_distributor._handle_mirror(cluster_relation)
        unit_databag = cluster_relation.data[manager.charm.unit]

        # adds hostname as expected
        assert "mirror-karkat" in unit_databag
        assert unit_databag["mirror-karkat"] == "empty"
        logger_info.assert_any_call("added mirror-karkat to mirror")

        # obviously adds with mirror up
        assert "mirror-terezi" in unit_databag
        assert unit_databag["mirror-terezi"] == "empty"
        logger_info.assert_any_call("added mirror-terezi to mirror")

        # still adds with mirror down
        assert "mirror-gamzee" in unit_databag
        assert unit_databag["mirror-gamzee"] == "empty"
        logger_info.assert_any_call("added mirror-gamzee to mirror")

        # ensure we dont overwrite existing token
        assert "mirror-eridan" in unit_databag
        assert unit_databag["mirror-eridan"] == "example-token-xyz-123"
        call("added mirror-eridan to mirror") not in logger_info.call_args_list

        # host-name doesn't match hostname
        assert "mirror-equius" not in unit_databag
        call("added mirror-equius to mirror") not in logger_info.call_args_list

        # nodename similar but doesn't match hostname
        assert "mirror-tavros" not in unit_databag
        call("added mirror-tavros to mirror") not in logger_info.call_args_list

        # still adds with other data
        assert "mirror-sollux" in unit_databag
        assert unit_databag["mirror-sollux"] == "empty"
        logger_info.assert_any_call("added mirror-sollux to mirror")

        # in mirror, not in remote unit data
        assert "mirror-kanaya" in unit_databag
        assert unit_databag["mirror-kanaya"] == "egbert-lalonde-strider-harley"
        call("added mirror-kanaya to mirror") not in logger_info.call_args_list

        # already in mirror as empty
        assert "mirror-zapano" in unit_databag
        assert unit_databag["mirror-zapano"] == "empty"
        call("added mirror-zapano to mirror") not in logger_info.call_args_list

        assert logger_info.call_count == 4


@pytest.mark.parametrize("leader_before", [True, False])
@pytest.mark.parametrize("leader_after", [True, False])
def test_on_leader_elected(leader_before, leader_after):
    ctx = testing.Context(charm.TokenDistributor)
    local_unit_data = {}
    if leader_before:
        local_unit_data["mirror"] = "up"
    cluster_relation = testing.Relation(
        charm.CONTROL_RELATION, "worker-cluster", local_unit_data=local_unit_data
    )
    with (
        ctx(
            ctx.on.leader_elected(),
            testing.State(relations=[cluster_relation], leader=leader_after),
        ) as manager,
        patch.object(
            manager.charm.token_distributor, "_handle_mirror"
        ) as token_distributor_handle_mirror,
    ):
        cluster_relation = manager.charm.model.get_relation(charm.CONTROL_RELATION)
        unit_databag = cluster_relation.data[manager.charm.unit]
        if leader_before:
            assert unit_databag["mirror"] == "up"
        else:
            assert "mirror" not in unit_databag
        manager.run()
        unit_databag = cluster_relation.data[manager.charm.unit]
        if leader_after:
            token_distributor_handle_mirror.assert_called_once()
            # ensure mirror is up
            assert "mirror" in unit_databag
            assert unit_databag["mirror"] == "up"
        else:
            token_distributor_handle_mirror.assert_not_called()
            if leader_before:
                # mirror was up so it is now down
                assert "mirror" in unit_databag
                assert unit_databag["mirror"] == "down"
            else:
                # mirror was not in the databag so didn't need to be set to down
                assert "mirror" not in unit_databag


@pytest.mark.parametrize("leader", [True, False])
def test_on_token_relation_changed(leader):
    ctx = testing.Context(charm.TokenDistributor)
    cluster_relation = testing.Relation(
        charm.CONTROL_RELATION,
        "worker-cluster",
    )
    with (
        ctx(
            ctx.on.relation_changed(cluster_relation),
            testing.State(relations=[cluster_relation], leader=leader),
        ) as manager,
        patch.object(
            manager.charm.token_distributor, "_handle_mirror"
        ) as token_distributor_handle_mirror,
    ):
        manager.run()
        # ensure we only handle mirror if we are leader
        if leader:
            token_distributor_handle_mirror.assert_called_once()
        else:
            token_distributor_handle_mirror.assert_not_called()
