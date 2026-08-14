# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import os
from pathlib import Path
from typing import Generator

import jubilant
import pytest
import yaml

CHARM_PATH_ENV = "TOKEN_DISTRIBUTOR_CHARM_PATH"


@pytest.fixture(scope="module")
def app_name() -> str:
    metadata = yaml.safe_load(Path("./charmcraft.yaml").read_text())
    return metadata["name"]


@pytest.fixture(scope="module")
def charm_path() -> Path | str:
    if env_val := os.environ.get(CHARM_PATH_ENV):
        return env_val
    if path := next(Path.cwd().glob("*.charm"), None):
        return path
    raise EnvironmentError(f"{CHARM_PATH_ENV} not set and no .charm found in cwd")


@pytest.fixture(scope="module")
def juju() -> Generator[jubilant.Juju, None, None]:
    controller = os.environ.get("LXD_CONTROLLER", "concierge-lxd")
    with jubilant.temp_model(
        controller=controller,
        config={"image-stream": "daily", "enable-os-upgrade": "false"},
    ) as juju:
        juju.wait_timeout = 15 * 60
        yield juju
