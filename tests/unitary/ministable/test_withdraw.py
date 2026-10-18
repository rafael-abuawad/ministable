import boa

from tests.utils.constants import ETH, ORACLE_TIMEOUT, POSITION_DEBT
from tests.utils.helpers import filter_logs


def test_withdraw_without_debt(stable, borrower):
    """Money Flow: stable ETH → borrower."""
    stable.deposit(value=ETH, sender=borrower)
    borrower_eth = boa.env.get_balance(borrower)

    stable.withdraw(ETH, sender=borrower)

    assert stable.collateral(borrower) == 0
    assert boa.env.get_balance(stable.address) == 0
    assert boa.env.get_balance(borrower) == borrower_eth + ETH


def test_withdraw_emits_event(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    stable.withdraw(ETH, sender=borrower)

    logs = filter_logs(stable, "Withdraw")
    assert len(logs) == 1
    assert logs[0].user == borrower
    assert logs[0].amount == ETH


def test_withdraw_keeping_ratio(stable, borrower):
    stable.deposit(value=2 * ETH, sender=borrower)
    stable.mint(POSITION_DEBT, sender=borrower)

    stable.withdraw(ETH, sender=borrower)

    assert stable.collateral(borrower) == ETH
    assert stable.collat_ratio(borrower) == 2 * 10**18


def test_withdraw_down_to_limit(stable, borrower_position):
    """1000 mUSD at $2000 needs exactly 0.75 ETH."""
    borrower = borrower_position

    stable.withdraw(ETH // 4, sender=borrower)

    assert stable.collateral(borrower) == 3 * ETH // 4
    assert stable.collat_ratio(borrower) == 15 * 10**17


def test_withdraw_one_wei_past_limit_reverts(stable, borrower_position):
    with boa.reverts(dev="[ministable] undercollateralized"):
        stable.withdraw(ETH // 4 + 1, sender=borrower_position)


def test_withdraw_breaking_ratio_reverts(stable, borrower_position):
    with boa.reverts(dev="[ministable] undercollateralized"):
        stable.withdraw(ETH // 2, sender=borrower_position)


def test_withdraw_more_than_collateral_reverts(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    with boa.reverts():
        stable.withdraw(ETH + 1, sender=borrower)


def test_withdraw_other_users_collateral_reverts(stable, borrower, liquidator):
    stable.deposit(value=ETH, sender=borrower)

    with boa.reverts():
        stable.withdraw(ETH, sender=liquidator)


def test_withdraw_without_debt_ignores_oracle(stable, oracle, borrower):
    """Debt-free positions never read the price, so a dead feed can't lock funds."""
    stable.deposit(value=ETH, sender=borrower)
    oracle.set_answer(0)
    boa.env.time_travel(seconds=ORACLE_TIMEOUT + 1)

    stable.withdraw(ETH, sender=borrower)

    assert stable.collateral(borrower) == 0


def test_withdraw_to_rejecting_contract_reverts(stable, receiver):
    receiver.deposit(value=ETH)
    receiver.set_accept_eth(False)

    with boa.reverts():
        receiver.withdraw(ETH)

    assert stable.collateral(receiver.address) == ETH


def test_withdraw_reentrancy_reverts(stable, receiver):
    """`__default__` of the receiver calls `withdraw` again while ETH is in flight."""
    receiver.deposit(value=2 * ETH)
    receiver.set_reenter(True)

    with boa.reverts():
        receiver.withdraw(ETH)

    assert stable.collateral(receiver.address) == 2 * ETH
    assert boa.env.get_balance(stable.address) == 2 * ETH


def test_withdraw_to_contract(stable, receiver):
    receiver_eth = boa.env.get_balance(receiver.address)
    receiver.deposit(value=ETH)

    receiver.withdraw(ETH)

    assert stable.collateral(receiver.address) == 0
    assert boa.env.get_balance(receiver.address) == receiver_eth + ETH
