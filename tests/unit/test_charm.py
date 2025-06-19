# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
#


from ops import testing

from charm import TokenDistributor


def test_start():
    # Arrange:
    ctx = testing.Context(TokenDistributor)
    # Act:
    state_out = ctx.run(ctx.on.start(), testing.State())
    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()
