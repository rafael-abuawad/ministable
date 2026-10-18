import boa
import pytest

from tests.utils.constants import (
    ETH,
    ETH_USD_PRICE,
    LIQUIDATION_PENALTY,
    LIQUIDATION_PRICE,
    MAX_STABILITY_FEE,
    MAX_UINT256,
    MIN_COLLAT_RATIO,
    POSITION_COLLATERAL,
    POSITION_DEBT,
    PRECISION,
    YEAR,
)
from tests.utils.helpers import deploy_stable, filter_logs, liquidation, to_feed_price

# At $1400 the default position (1 ETH, 1000 mUSD) is at 140%: repaying
# 250 mUSD for 275 $ of ETH brings it back to exactly 150%.
PARTIAL_PRICE = to_feed_price(1400)
PARTIAL_REPAY = 250 * ETH
# At $1000 the position is at 100%: its ETH covers 1000 / 1.1 mUSD at 110%.
INSOLVENT_PRICE = to_feed_price(1000)


# ================= Partial liquidation =================


def test_partial_liquidation_restores_min_ratio(
    stable, oracle, borrower_position, funded_liquidator
):
    """Money Flow: liquidator mUSD → burned, 110% of it in borrower ETH → liquidator."""
    borrower, liquidator = borrower_position, funded_liquidator
    liquidator_eth = boa.env.get_balance(liquidator)
    supply = stable.totalSupply()
    oracle.set_answer(PARTIAL_PRICE)
    repaid, seized, _ = liquidation(POSITION_COLLATERAL, POSITION_DEBT, PARTIAL_PRICE, MAX_UINT256)
    assert repaid == PARTIAL_REPAY

    assert stable.liquidate(borrower, MAX_UINT256, sender=liquidator) == repaid

    assert stable.debt(borrower) == POSITION_DEBT - repaid
    assert stable.collateral(borrower) == POSITION_COLLATERAL - seized
    assert stable.collat_ratio(borrower) >= MIN_COLLAT_RATIO
    assert stable.collat_ratio(borrower) < MIN_COLLAT_RATIO + 10**9
    assert stable.balanceOf(liquidator) == POSITION_DEBT - repaid
    assert stable.totalSupply() == supply - repaid
    assert boa.env.get_balance(liquidator) == liquidator_eth + seized
    # The liquidator's bonus: $1.10 of ETH per $1 repaid.
    assert repaid * 11 // 10 - 1400 < seized * 1400 <= repaid * 11 // 10


def test_over_ask_is_capped(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(PARTIAL_PRICE)

    stable.liquidate(borrower_position, POSITION_DEBT, sender=funded_liquidator)

    assert stable.debt(borrower_position) == POSITION_DEBT - PARTIAL_REPAY


def test_small_repay_improves_ratio(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(PARTIAL_PRICE)
    ratio = stable.collat_ratio(borrower_position)

    stable.liquidate(borrower_position, 100 * ETH, sender=funded_liquidator)

    assert stable.debt(borrower_position) == POSITION_DEBT - 100 * ETH
    assert ratio < stable.collat_ratio(borrower_position) < MIN_COLLAT_RATIO

    # Still unhealthy, so anyone can finish the job.
    stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)
    assert stable.collat_ratio(borrower_position) >= MIN_COLLAT_RATIO


def test_zero_repay_reverts(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(PARTIAL_PRICE)

    with boa.reverts(dev="[ministable] zero repay"):
        stable.liquidate(borrower_position, 0, sender=funded_liquidator)


def test_liquidate_emits_events(stable, oracle, borrower_position, funded_liquidator):
    borrower, liquidator = borrower_position, funded_liquidator
    oracle.set_answer(PARTIAL_PRICE)
    _, seized, _ = liquidation(POSITION_COLLATERAL, POSITION_DEBT, PARTIAL_PRICE, MAX_UINT256)

    stable.liquidate(borrower, MAX_UINT256, sender=liquidator)
    logs = filter_logs(stable, "Liquidate")
    transfer_logs = filter_logs(stable, "Transfer")

    assert len(logs) == 1
    assert (logs[0].liquidator, logs[0].user) == (liquidator, borrower)
    assert (logs[0].repaid, logs[0].seized, logs[0].written_off) == (PARTIAL_REPAY, seized, 0)
    assert len(transfer_logs) == 1
    assert transfer_logs[0].sender == liquidator
    assert transfer_logs[0].value == PARTIAL_REPAY


def test_liquidate_leaves_liquidator_position_untouched(
    stable, oracle, borrower_position, funded_liquidator
):
    liquidator = funded_liquidator
    collateral, debt = stable.collateral(liquidator), stable.debt(liquidator)
    oracle.set_answer(PARTIAL_PRICE)

    stable.liquidate(borrower_position, MAX_UINT256, sender=liquidator)

    assert stable.collateral(liquidator) == collateral
    assert stable.debt(liquidator) == debt


# ================= Insolvent positions and bad debt =================


def test_insolvent_position_is_closed_and_written_off(
    stable, oracle, borrower_position, funded_liquidator
):
    borrower, liquidator = borrower_position, funded_liquidator
    liquidator_eth = boa.env.get_balance(liquidator)
    oracle.set_answer(INSOLVENT_PRICE)
    repaid, seized, written_off = liquidation(
        POSITION_COLLATERAL, POSITION_DEBT, INSOLVENT_PRICE, MAX_UINT256
    )
    assert seized == POSITION_COLLATERAL
    assert repaid == 1000 * ETH * PRECISION // LIQUIDATION_PENALTY

    stable.liquidate(borrower, MAX_UINT256, sender=liquidator)
    log = filter_logs(stable, "Liquidate")[0]

    assert (log.repaid, log.seized, log.written_off) == (repaid, seized, written_off)
    assert stable.debt(borrower) == 0
    assert stable.debt_shares(borrower) == 0
    assert stable.collateral(borrower) == 0
    assert boa.env.get_balance(liquidator) == liquidator_eth + POSITION_COLLATERAL
    # No surplus to absorb it: the gap between supply and debt is bad debt.
    assert stable.bad_debt() == written_off
    # Every mUSD is still owed by a position or recorded as bad debt.
    assert stable.totalSupply() == stable.debt(liquidator) + stable.bad_debt()


def test_insolvent_requires_full_repay(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(INSOLVENT_PRICE)
    repaid, _, _ = liquidation(POSITION_COLLATERAL, POSITION_DEBT, INSOLVENT_PRICE, MAX_UINT256)

    with boa.reverts(dev="[ministable] repay too small"):
        stable.liquidate(borrower_position, repaid - 1, sender=funded_liquidator)

    stable.liquidate(borrower_position, repaid, sender=funded_liquidator)


# ================= Surplus and reserve as a backstop =================


@pytest.fixture
def fee_stable(oracle, borrower, liquidator, recipient):
    """A 10%-a-year deployment where `recipient` runs a large, safe position
    for a year, building up a surplus, and `borrower` holds the default position."""
    oracle.set_answer(ETH_USD_PRICE)
    stable = deploy_stable(oracle.address, fee=MAX_STABILITY_FEE)
    stable.deposit(value=20 * ETH, sender=recipient)
    stable.mint(10_000 * ETH, sender=recipient)
    stable.transfer(liquidator, 2_000 * ETH, sender=recipient)
    stable.deposit(value=POSITION_COLLATERAL, sender=borrower)
    stable.mint(POSITION_DEBT, sender=borrower)
    return stable


def _wait(oracle, seconds, price=ETH_USD_PRICE):
    boa.env.time_travel(seconds=seconds)
    oracle.set_answer(price)


def test_surplus_absorbs_bad_debt(fee_stable, oracle, borrower, liquidator):
    _wait(oracle, YEAR, INSOLVENT_PRICE)
    fee_stable.mint(0, sender=liquidator)
    surplus = fee_stable.surplus()
    assert surplus > 1000 * ETH  # ~10% of 11,000 mUSD

    fee_stable.liquidate(borrower, MAX_UINT256, sender=liquidator)
    written_off = filter_logs(fee_stable, "Liquidate")[0].written_off
    settled = filter_logs(fee_stable, "Settle")[0].amount

    assert written_off > 0
    assert settled == written_off
    assert fee_stable.bad_debt() == 0
    assert fee_stable.surplus() == surplus - written_off


def test_later_interest_pays_down_bad_debt(fee_stable, oracle, borrower, liquidator):
    oracle.set_answer(INSOLVENT_PRICE)
    fee_stable.liquidate(borrower, MAX_UINT256, sender=liquidator)
    bad_debt = fee_stable.bad_debt()
    assert bad_debt > 0
    assert fee_stable.surplus() == 0

    _wait(oracle, YEAR // 12, INSOLVENT_PRICE)
    fee_stable.mint(0, sender=liquidator)  # any accruing call settles

    assert fee_stable.bad_debt() < bad_debt
    assert fee_stable.surplus() == 0


def test_cover_bad_debt_from_reserve(fee_stable, oracle, borrower, liquidator, recipient):
    # Interest is sold for ETH, filling the reserve.
    _wait(oracle, YEAR)
    fee_stable.mint(0, sender=recipient)
    eth_paid = fee_stable.surplus() * PRECISION // (ETH_USD_PRICE * 10**10)
    fee_stable.buy_surplus(value=eth_paid, sender=recipient)
    reserve = fee_stable.reserve()

    # Then a position goes insolvent with no surplus left to absorb it.
    oracle.set_answer(INSOLVENT_PRICE)
    fee_stable.liquidate(borrower, MAX_UINT256, sender=liquidator)
    bad_debt = fee_stable.bad_debt()
    assert bad_debt > 0

    liquidator_eth = boa.env.get_balance(liquidator)
    eth = fee_stable.cover_bad_debt(bad_debt, sender=liquidator)
    log = filter_logs(fee_stable, "CoverBadDebt")[0]

    assert eth == bad_debt * PRECISION // (INSOLVENT_PRICE * 10**10)
    assert (log.caller, log.amount, log.eth) == (liquidator, bad_debt, eth)
    assert fee_stable.bad_debt() == 0
    assert fee_stable.reserve() == reserve - eth
    assert boa.env.get_balance(liquidator) == liquidator_eth + eth


def test_cover_more_than_bad_debt_reverts(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(INSOLVENT_PRICE)
    stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)

    with boa.reverts(dev="[ministable] cover exceeds bad debt"):
        stable.cover_bad_debt(stable.bad_debt() + 1, sender=funded_liquidator)


def test_cover_without_reserve_reverts(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(INSOLVENT_PRICE)
    stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)

    with boa.reverts(dev="[ministable] not enough reserve"):
        stable.cover_bad_debt(stable.bad_debt(), sender=funded_liquidator)


def test_cover_zero_reverts(stable, funded_liquidator):
    with boa.reverts(dev="[ministable] zero cover"):
        stable.cover_bad_debt(0, sender=funded_liquidator)


# ================= When liquidation is refused =================


def test_liquidate_at_exact_min_ratio_reverts(
    stable, oracle, borrower_position, funded_liquidator
):
    oracle.set_answer(LIQUIDATION_PRICE)
    assert stable.collat_ratio(borrower_position) == MIN_COLLAT_RATIO

    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)


def test_liquidate_just_below_min_ratio(
    stable, oracle, borrower_position, funded_liquidator
):
    oracle.set_answer(LIQUIDATION_PRICE - 1)

    repaid = stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)

    assert 0 < repaid < ETH
    assert stable.collat_ratio(borrower_position) >= MIN_COLLAT_RATIO


def test_liquidate_healthy_reverts(stable, borrower_position, funded_liquidator):
    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)


def test_liquidate_debt_free_position_reverts(stable, borrower, funded_liquidator):
    stable.deposit(value=ETH, sender=borrower)

    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower, MAX_UINT256, sender=funded_liquidator)


def test_liquidate_without_enough_musd_reverts(
    stable, oracle, borrower_position, liquidator
):
    oracle.set_answer(PARTIAL_PRICE)

    with boa.reverts(dev="[erc20] burn amount exceeds balance"):
        stable.liquidate(borrower_position, MAX_UINT256, sender=liquidator)

    assert stable.debt(borrower_position) == POSITION_DEBT


def test_liquidate_twice_reverts(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(PARTIAL_PRICE)
    stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)

    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)


def test_liquidate_with_stale_price_reverts(
    stable, oracle, borrower_position, funded_liquidator
):
    oracle.set_answer(PARTIAL_PRICE)
    boa.env.time_travel(seconds=stable.ORACLE_TIMEOUT() + 1)

    with boa.reverts(dev="[ministable] stale price"):
        stable.liquidate(borrower_position, MAX_UINT256, sender=funded_liquidator)


def test_self_liquidation(stable, oracle, borrower_position):
    """An underwater borrower can liquidate themselves, keeping the bonus."""
    borrower = borrower_position
    borrower_eth = boa.env.get_balance(borrower)
    oracle.set_answer(PARTIAL_PRICE)
    _, seized, _ = liquidation(POSITION_COLLATERAL, POSITION_DEBT, PARTIAL_PRICE, MAX_UINT256)

    stable.liquidate(borrower, MAX_UINT256, sender=borrower)

    assert stable.debt(borrower) == POSITION_DEBT - PARTIAL_REPAY
    assert stable.balanceOf(borrower) == POSITION_DEBT - PARTIAL_REPAY
    assert boa.env.get_balance(borrower) == borrower_eth + seized
