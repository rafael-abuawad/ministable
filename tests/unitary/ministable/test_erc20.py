import boa

from tests.utils.constants import ETH, POSITION_DEBT
from tests.utils.helpers import filter_logs


def test_transfer(stable, borrower_position, recipient):
    stable.transfer(recipient, 100 * ETH, sender=borrower_position)

    assert stable.balanceOf(recipient) == 100 * ETH
    assert stable.balanceOf(borrower_position) == POSITION_DEBT - 100 * ETH
    assert stable.totalSupply() == POSITION_DEBT


def test_transfer_emits_event(stable, borrower_position, recipient):
    stable.transfer(recipient, 100 * ETH, sender=borrower_position)

    logs = filter_logs(stable, "Transfer")
    assert len(logs) == 1
    assert logs[0].sender == borrower_position
    assert logs[0].receiver == recipient
    assert logs[0].value == 100 * ETH


def test_transfer_does_not_move_debt(stable, borrower_position, recipient):
    stable.transfer(recipient, POSITION_DEBT, sender=borrower_position)

    assert stable.debt(borrower_position) == POSITION_DEBT
    assert stable.debt(recipient) == 0


def test_transfer_exceeding_balance_reverts(stable, borrower_position, recipient):
    with boa.reverts(dev="[erc20] transfer amount exceeds balance"):
        stable.transfer(recipient, POSITION_DEBT + 1, sender=borrower_position)


def test_transfer_to_zero_address_reverts(stable, borrower_position):
    with boa.reverts(dev="[erc20] transfer to the zero address"):
        stable.transfer(boa.eval("empty(address)"), 1, sender=borrower_position)


def test_approve(stable, borrower, recipient):
    stable.approve(recipient, 100 * ETH, sender=borrower)

    # Read logs before any other call: `get_logs` reflects the last call only.
    logs = filter_logs(stable, "Approval")
    assert len(logs) == 1
    assert logs[0].owner == borrower
    assert logs[0].spender == recipient
    assert logs[0].value == 100 * ETH
    assert stable.allowance(borrower, recipient) == 100 * ETH


def test_transfer_from(stable, borrower_position, recipient):
    stable.approve(recipient, 100 * ETH, sender=borrower_position)

    stable.transferFrom(borrower_position, recipient, 60 * ETH, sender=recipient)

    assert stable.balanceOf(recipient) == 60 * ETH
    assert stable.allowance(borrower_position, recipient) == 40 * ETH


def test_transfer_from_infinite_allowance_not_spent(stable, borrower_position, recipient):
    max_uint = 2**256 - 1
    stable.approve(recipient, max_uint, sender=borrower_position)

    stable.transferFrom(borrower_position, recipient, 60 * ETH, sender=recipient)

    assert stable.allowance(borrower_position, recipient) == max_uint


def test_transfer_from_exceeding_allowance_reverts(stable, borrower_position, recipient):
    stable.approve(recipient, 10 * ETH, sender=borrower_position)

    with boa.reverts(dev="[erc20] insufficient allowance"):
        stable.transferFrom(borrower_position, recipient, 10 * ETH + 1, sender=recipient)
