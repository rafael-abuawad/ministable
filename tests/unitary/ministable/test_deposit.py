import boa
import pytest
from eth.exceptions import Revert

from tests.utils.constants import ETH
from tests.utils.helpers import filter_logs


def test_deposit_locks_collateral(stable, borrower):
    """Money Flow: borrower ETH → stable."""
    # ================= Capture initial state =================
    borrower_eth = boa.env.get_balance(borrower)

    # ================= Execute =================
    stable.deposit(value=ETH, sender=borrower)

    # ================= Verify state and money flows =================
    assert stable.collateral(borrower) == ETH
    assert stable.debt(borrower) == 0
    assert boa.env.get_balance(stable.address) == ETH
    assert boa.env.get_balance(borrower) == borrower_eth - ETH


def test_deposit_emits_event(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    logs = filter_logs(stable, "Deposit")
    assert len(logs) == 1
    assert logs[0].user == borrower
    assert logs[0].amount == ETH


def test_deposit_accumulates(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)
    stable.deposit(value=2 * ETH, sender=borrower)

    assert stable.collateral(borrower) == 3 * ETH
    assert boa.env.get_balance(stable.address) == 3 * ETH


def test_plain_transfer_is_deposit(stable, borrower):
    """Money Flow: borrower ETH → stable via `__default__`."""
    boa.env.raw_call(stable.address, sender=borrower, value=ETH)

    assert stable.collateral(borrower) == ETH
    assert boa.env.get_balance(stable.address) == ETH


def test_plain_transfer_emits_event(stable, borrower):
    computation = boa.env.raw_call(stable.address, sender=borrower, value=ETH)

    logs = filter_logs(stable, "Deposit", computation)
    assert len(logs) == 1
    assert logs[0].user == borrower
    assert logs[0].amount == ETH


def test_deposit_is_per_account(stable, borrower, liquidator):
    stable.deposit(value=ETH, sender=borrower)
    stable.deposit(value=2 * ETH, sender=liquidator)

    assert stable.collateral(borrower) == ETH
    assert stable.collateral(liquidator) == 2 * ETH


def test_zero_deposit_reverts(stable, borrower):
    with boa.reverts("ministable: zero deposit"):
        stable.deposit(sender=borrower)


def test_zero_plain_transfer_reverts(stable, borrower):
    # `env.raw_call` surfaces the raw py-evm revert, not a BoaError.
    with pytest.raises(Revert, match="ministable: zero deposit"):
        boa.env.raw_call(stable.address, sender=borrower)
