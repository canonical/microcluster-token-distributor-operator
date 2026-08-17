#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jubilant

logger = logging.getLogger(__name__)


def test_build_and_deploy(juju: jubilant.Juju, charm_path: Path, app_name: str):
    """Deploy the charm and wait for active/idle status."""
    juju.deploy(charm_path, app=app_name)
    juju.wait(jubilant.all_active)


def test_token_distributor_multiple_microovn(juju: jubilant.Juju, charm_path: Path, app_name: str):
    juju.deploy(charm_path, app=app_name)
    microovns = ["microovn-terezi", "microovn-vriska"]

    for microovn in microovns:
        juju.deploy("microovn", channel="latest/edge", app=microovn)
        juju.integrate(microovn, app_name)

    juju.wait(jubilant.all_active, timeout=600)
    juju.wait(jubilant.all_agents_idle, timeout=600)

    cluster_output = juju.exec("microovn cluster list --format csv", unit=f"{microovns[0]}/0")
    assert len(cluster_output.stdout.split("\n")) == 2

    outputs = []
    for microovn in microovns:
        cluster_output = juju.exec("microovn cluster list --format csv", unit=f"{microovn}/0")
        outputs.append("\n".join(sorted(cluster_output.stdout.split("\n"))))

    assert outputs[0] == outputs[1]
