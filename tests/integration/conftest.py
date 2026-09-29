# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import re
from pathlib import Path
from typing import Generator

import jubilant
import pytest
import yaml

CHARM_PATH_ENV = "TOKEN_DISTRIBUTOR_CHARM_PATH"
BASE_RE = re.compile(r"ubuntu@\d+\.\d+")


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
def charm_base(charm_path: Path | str) -> str:
    """Return the base (e.g. ``ubuntu@26.04``) encoded in the charm filename."""
    match = BASE_RE.search(Path(charm_path).name)
    if not match:
        raise ValueError(f"Could not determine charm base for: {charm_path}")
    return match.group(0)


@pytest.fixture(scope="module")
def juju(charm_base: str) -> Generator[jubilant.Juju, None, None]:
    controller = os.environ.get("LXD_CONTROLLER", "concierge-lxd")
    with jubilant.temp_model(
        controller=controller,
        config={
            "default-base": charm_base,
            "image-stream": "daily",
            "enable-os-upgrade": "false",
        },
    ) as juju:
        juju.wait_timeout = 15 * 60
        yield juju
