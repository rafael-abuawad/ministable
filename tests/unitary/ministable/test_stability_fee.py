import boa
import pytest

from tests.utils.constants import (
    ETH,
    ETH_USD_PRICE,
    MAX_STABILITY_FEE,
    POSITION_COLLATERAL,
    POSITION_DEBT,
    PRECISION,
    YEAR,
)
from tests.utils.helpers import deploy_stable, filter_logs


def _index_after(seconds: int, fee: int = MAX_STABILITY_FEE) -> int:
    return PRECISION + PRECISION * fee * seconds // PRECISION


def _debt_after(principal: int, seconds: int) -> int:
    """Debt of a position that minted `principal` at index 1e18 (mirrors `_debt`)."""
    return -(-principal * _index_after(seconds) // PRECISION)


def _wait(oracle, seconds: int):
    """Let time pass, keeping the oracle fresh."""
    boa.env.time_travel(seconds=seconds)
    oracle.set_answer(ETH_USD_PRICE)


@pytest.fixture
def fee_stable(oracle):
    oracle.set_answer(ETH_USD_PRICE)
    return deploy_stable(oracle.address, fee=MAX_STABILITY_FEE)


@pytest.fixture
def fee_position(fee_stable, borrower):
    fee_stable.deposit(value=POSITION_COLLATERAL, sender=borrower)
    fee_stable.mint(POSITION_DEBT, sender=borrower)
    return borrower


def test_fee_above_cap_reverts(oracle):
    with boa.reverts(dev="[cdp_native] stability fee too high"):
        deploy_stable(oracle.address, fee=MAX_STABILITY_FEE + 1)


def test_parameters(fee_stable):
    assert fee_stable.STABILITY_FEE() == MAX_STABILITY_FEE
    assert fee_stable.MAX_STABILITY_FEE() == MAX_STABILITY_FEE
    assert fee_stable.rate_index() == PRECISION


def test_debt_grows_with_time(fee_stable, oracle, fee_position):
    _wait(oracle, YEAR)

    # The view includes interest that hasn't been accrued yet.
    assert fee_stable.debt(fee_position) == _debt_after(POSITION_DEBT, YEAR)
    assert fee_stable.debt(fee_position) > POSITION_DEBT * 109 // 100


def test_accrual_mints_interest_to_surplus(fee_stable, oracle, fee_position):
    _wait(oracle, YEAR)
    fee_stable.mint(0, sender=fee_position)
    logs = filter_logs(fee_stable, "Accrue")

    interest = fee_stable.debt(fee_position) - POSITION_DEBT
    assert fee_stable.rate_index() == _index_after(YEAR)
    assert interest - 1 <= fee_stable.surplus() <= interest
    assert fee_stable.balanceOf(fee_stable.address) == fee_stable.surplus()
    assert logs[0].amount == fee_stable.surplus()


def test_debt_free_position_does_not_accrue(fee_stable, oracle, borrower):
    fee_stable.deposit(value=ETH, sender=borrower)
    _wait(oracle, YEAR)
    fee_stable.withdraw(ETH, sender=borrower)

    assert fee_stable.debt(borrower) == 0
    assert fee_stable.surplus() == 0


def test_interest_lowers_collat_ratio(fee_stable, oracle, fee_position):
    ratio = fee_stable.collat_ratio(fee_position)
    _wait(oracle, YEAR)

    assert fee_stable.collat_ratio(fee_position) < ratio


def test_full_repay_with_surplus_bought(fee_stable, oracle, fee_position):
    """Interest is minted to the surplus, so a borrower buys it there to close out."""
    borrower = fee_position
    _wait(oracle, YEAR)
    fee_stable.mint(0, sender=borrower)
    debt = fee_stable.debt(borrower)
    missing = debt - fee_stable.balanceOf(borrower)

    eth = -(-missing * PRECISION // (ETH_USD_PRICE * 10**10))
    fee_stable.buy_surplus(value=eth, sender=borrower)
    fee_stable.burn(debt, sender=borrower)
    fee_stable.withdraw(POSITION_COLLATERAL, sender=borrower)

    assert fee_stable.debt(borrower) == 0
    assert fee_stable.debt_shares(borrower) == 0
    assert fee_stable.total_debt_shares() == 0
    assert fee_stable.collateral(borrower) == 0
    assert fee_stable.reserve() == eth
    assert boa.env.get_balance(fee_stable.address) == eth


def test_partial_repay(fee_stable, oracle, fee_position):
    _wait(oracle, YEAR)
    debt = fee_stable.debt(fee_position)

    fee_stable.burn(POSITION_DEBT // 2, sender=fee_position)

    remaining = fee_stable.debt(fee_position)
    # Partial repays round the shares removed down, never in the borrower's favour.
    assert debt - POSITION_DEBT // 2 <= remaining <= debt - POSITION_DEBT // 2 + 1


def test_burn_more_than_debt_reverts(fee_stable, fee_position):
    with boa.reverts(dev="[cdp_native] repay exceeds debt"):
        fee_stable.burn(POSITION_DEBT + 1, sender=fee_position)


def test_buy_surplus(fee_stable, oracle, fee_position, recipient):
    _wait(oracle, YEAR)
    fee_stable.mint(0, sender=fee_position)
    surplus = fee_stable.surplus()
    eth = ETH // 100  # $20 at $2000

    out = fee_stable.buy_surplus(value=eth, sender=recipient)
    log = filter_logs(fee_stable, "BuySurplus")[0]

    assert out == 20 * ETH
    assert fee_stable.balanceOf(recipient) == out
    assert fee_stable.surplus() == surplus - out
    assert fee_stable.reserve() == eth
    assert (log.buyer, log.eth, log.amount) == (recipient, eth, out)


def test_buy_more_than_surplus_reverts(fee_stable, oracle, fee_position, recipient):
    _wait(oracle, YEAR)

    with boa.reverts(dev="[cdp_native] not enough surplus"):
        fee_stable.buy_surplus(value=ETH, sender=recipient)


def test_buy_nothing_reverts(fee_stable, recipient):
    with boa.reverts(dev="[cdp_native] zero purchase"):
        fee_stable.buy_surplus(value=0, sender=recipient)


def test_interest_free_deployment_never_accrues(stable, oracle, borrower_position):
    _wait(oracle, YEAR)
    stable.mint(0, sender=borrower_position)

    assert stable.debt(borrower_position) == POSITION_DEBT
    assert stable.surplus() == 0
