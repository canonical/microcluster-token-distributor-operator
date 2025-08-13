#!/usr/bin/env python3
import os
from unittest.mock import patch

import charms.microcluster_token_distributor.v0.token_distributor as token_distributor


def test_mirror_id():
    assert token_distributor.mirror_id("test") == "mirror-test"
    assert token_distributor.mirror_id("nepeta") == "mirror-nepeta"
    assert token_distributor.mirror_id("key") == "mirror-key"
    assert token_distributor.mirror_id("413key612") == "mirror-413key612"
    assert token_distributor.mirror_id("-") == "mirror--"


@patch.object(token_distributor.os, "uname")
def test_get_hostname(os_uname):
    for nodename in ["vriska-prospit-scratch", "jasper-small-cat", "microovn-ceph-hpc"]:
        fake_uname = os.uname_result(["Linux", nodename, "6.11.0", "#29-24.04.1", "x86_64"])
        os_uname.return_value = fake_uname
        assert token_distributor.get_hostname() == nodename
