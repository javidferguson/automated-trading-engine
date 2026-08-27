"""Paper-account and replay gating."""

import pytest

from trading_engine.execution.safety import (
    LiveAccountError,
    ReplayTradeError,
    assert_can_trade,
    assert_paper_account,
)
from trading_engine.models import DataMode


class FakeIB:
    def __init__(self, accounts):
        self._accounts = accounts

    def managedAccounts(self):
        return self._accounts


def test_paper_accounts_pass():
    assert assert_paper_account(FakeIB(["DU1234567"])) == ["DU1234567"]


def test_advisor_paper_accounts_pass():
    assert assert_paper_account(FakeIB(["DF7654321"])) == ["DF7654321"]


def test_live_account_is_rejected():
    with pytest.raises(LiveAccountError, match="Non-paper account"):
        assert_paper_account(FakeIB(["U1234567"]))


def test_any_live_account_in_the_set_is_rejected():
    """A paper account alongside a live one is still a refusal."""
    with pytest.raises(LiveAccountError, match="U7654321"):
        assert_paper_account(FakeIB(["DU1234567", "U7654321"]))


def test_no_accounts_is_rejected():
    """Absence of proof is not proof of absence -- refuse rather than assume."""
    with pytest.raises(LiveAccountError, match="No managed accounts"):
        assert_paper_account(FakeIB([]))


def test_config_declaring_live_is_rejected_even_with_paper_accounts():
    with pytest.raises(LiveAccountError, match="paper-only"):
        assert_paper_account(FakeIB(["DU1234567"]), config_is_paper=False)


@pytest.mark.parametrize("mode", [DataMode.REALTIME, DataMode.DELAYED])
def test_live_data_modes_may_trade(mode):
    assert_can_trade(mode)  # does not raise


def test_replay_mode_cannot_trade():
    with pytest.raises(ReplayTradeError, match="historical"):
        assert_can_trade(DataMode.REPLAY)
