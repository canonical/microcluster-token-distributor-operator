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
