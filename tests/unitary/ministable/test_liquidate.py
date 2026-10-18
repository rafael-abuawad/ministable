import boa

from tests.utils.constants import (
    ETH,
    LIQUIDATION_PRICE,
    MIN_COLLAT_RATIO,
    POSITION_COLLATERAL,
    POSITION_DEBT,
)
from tests.utils.helpers import filter_logs, to_feed_price


def test_liquidate_after_price_drop(
    stable, oracle, borrower_position, funded_liquidator
):
    """Money Flow: liquidator mUSD → burned, borrower ETH → liquidator."""
    borrower, liquidator = borrower_position, funded_liquidator

    # ================= Capture initial state =================
    liquidator_eth = boa.env.get_balance(liquidator)
    stable_eth = boa.env.get_balance(stable.address)
    supply = stable.totalSupply()

    # ================= Setup =================
    oracle.set_answer(to_feed_price(1400))
    assert stable.collat_ratio(borrower) < MIN_COLLAT_RATIO

    # ================= Execute =================
    stable.liquidate(borrower, sender=liquidator)

    # ================= Verify state and money flows =================
    assert stable.debt(borrower) == 0
    assert stable.collateral(borrower) == 0
    assert stable.balanceOf(liquidator) == 0
    assert stable.balanceOf(borrower) == POSITION_DEBT  # borrower keeps the minted mUSD
    assert stable.totalSupply() == supply - POSITION_DEBT
    assert boa.env.get_balance(liquidator) == liquidator_eth + POSITION_COLLATERAL
    assert boa.env.get_balance(stable.address) == stable_eth - POSITION_COLLATERAL


def test_liquidate_emits_events(stable, oracle, borrower_position, funded_liquidator):
    borrower, liquidator = borrower_position, funded_liquidator
    oracle.set_answer(to_feed_price(1400))

    stable.liquidate(borrower, sender=liquidator)

    logs = filter_logs(stable, "Liquidate")
    assert len(logs) == 1
    assert logs[0].liquidator == liquidator
    assert logs[0].user == borrower
    assert logs[0].debt == POSITION_DEBT
    assert logs[0].collateral == POSITION_COLLATERAL

    transfer_logs = filter_logs(stable, "Transfer")
    assert len(transfer_logs) == 1
    assert transfer_logs[0].sender == liquidator
    assert transfer_logs[0].value == POSITION_DEBT


def test_liquidate_leaves_liquidator_position_untouched(
    stable, oracle, borrower_position, funded_liquidator
):
    liquidator = funded_liquidator
    collateral, debt = stable.collateral(liquidator), stable.debt(liquidator)
    oracle.set_answer(to_feed_price(1400))

    stable.liquidate(borrower_position, sender=liquidator)

    assert stable.collateral(liquidator) == collateral
    assert stable.debt(liquidator) == debt


def test_liquidate_at_exact_min_ratio_reverts(
    stable, oracle, borrower_position, funded_liquidator
):
    oracle.set_answer(LIQUIDATION_PRICE)
    assert stable.collat_ratio(borrower_position) == MIN_COLLAT_RATIO

    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower_position, sender=funded_liquidator)


def test_liquidate_just_below_min_ratio(
    stable, oracle, borrower_position, funded_liquidator
):
    oracle.set_answer(LIQUIDATION_PRICE - 1)

    stable.liquidate(borrower_position, sender=funded_liquidator)

    assert stable.debt(borrower_position) == 0


def test_liquidate_healthy_reverts(stable, borrower_position, funded_liquidator):
    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower_position, sender=funded_liquidator)


def test_liquidate_debt_free_position_reverts(stable, borrower, funded_liquidator):
    stable.deposit(value=ETH, sender=borrower)

    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower, sender=funded_liquidator)


def test_liquidate_without_enough_musd_reverts(
    stable, oracle, borrower_position, liquidator
):
    oracle.set_answer(to_feed_price(1400))

    with boa.reverts(dev="[erc20] burn amount exceeds balance"):
        stable.liquidate(borrower_position, sender=liquidator)

    assert stable.debt(borrower_position) == POSITION_DEBT


def test_liquidate_twice_reverts(stable, oracle, borrower_position, funded_liquidator):
    oracle.set_answer(to_feed_price(1400))
    stable.liquidate(borrower_position, sender=funded_liquidator)

    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower_position, sender=funded_liquidator)


def test_liquidate_with_stale_price_reverts(
    stable, oracle, borrower_position, funded_liquidator
):
    oracle.set_answer(to_feed_price(1400))
    boa.env.time_travel(seconds=stable.ORACLE_TIMEOUT() + 1)

    with boa.reverts(dev="[ministable] stale price"):
        stable.liquidate(borrower_position, sender=funded_liquidator)


def test_self_liquidation(stable, oracle, borrower_position):
    """An underwater borrower can close their own position."""
    borrower = borrower_position
    borrower_eth = boa.env.get_balance(borrower)
    oracle.set_answer(to_feed_price(1400))

    stable.liquidate(borrower, sender=borrower)

    assert stable.debt(borrower) == 0
    assert stable.balanceOf(borrower) == 0
    assert boa.env.get_balance(borrower) == borrower_eth + POSITION_COLLATERAL
