import boa

from tests.utils.constants import (
    ETH,
    ETH_USD_PRICE,
    MIN_COLLAT_RATIO,
    POSITION_COLLATERAL,
    POSITION_DEBT,
    PRECISION,
    REDEMPTION_FEE,
)
from tests.utils.helpers import filter_logs, to_feed_price


def _redeemed_eth(amount: int, feed_price: int = ETH_USD_PRICE) -> int:
    """ETH paid for `amount` mUSD (mirrors `redeem`)."""
    return amount * (PRECISION - REDEMPTION_FEE) // (feed_price * 10**10)


def test_redeem(stable, borrower_position, funded_liquidator):
    """Money Flow: redeemer mUSD → burned, $1 of the borrower's ETH less 0.5% → redeemer."""
    borrower, redeemer = borrower_position, funded_liquidator
    redeemer_eth = boa.env.get_balance(redeemer)
    supply = stable.totalSupply()
    amount = 400 * ETH
    eth = _redeemed_eth(amount)

    assert stable.redeem(borrower, amount, sender=redeemer) == eth

    assert eth == 199 * ETH // 1000  # $400 at $2000, less 0.5%
    assert stable.debt(borrower) == POSITION_DEBT - amount
    assert stable.collateral(borrower) == POSITION_COLLATERAL - eth
    assert stable.balanceOf(borrower) == POSITION_DEBT  # the borrower's mUSD is untouched
    assert stable.balanceOf(redeemer) == POSITION_DEBT - amount
    assert stable.totalSupply() == supply - amount
    assert boa.env.get_balance(redeemer) == redeemer_eth + eth


def test_fee_stays_with_borrower(stable, borrower_position, funded_liquidator):
    """The borrower loses $400 of debt and $398 of ETH: they keep $2 of value."""
    amount = 400 * ETH
    eth = stable.redeem(borrower_position, amount, sender=funded_liquidator)

    kept = amount - eth * 2000
    assert kept == amount * REDEMPTION_FEE // PRECISION


def test_redeem_raises_collat_ratio(stable, borrower_position, funded_liquidator):
    ratio = stable.collat_ratio(borrower_position)

    stable.redeem(borrower_position, 400 * ETH, sender=funded_liquidator)

    assert stable.collat_ratio(borrower_position) > ratio


def test_redeem_whole_debt(stable, borrower_position, funded_liquidator):
    eth = stable.redeem(borrower_position, POSITION_DEBT, sender=funded_liquidator)

    assert stable.debt(borrower_position) == 0
    assert stable.debt_shares(borrower_position) == 0
    assert stable.collateral(borrower_position) == POSITION_COLLATERAL - eth


def test_redeem_emits_event(stable, borrower_position, funded_liquidator):
    eth = stable.redeem(borrower_position, 400 * ETH, sender=funded_liquidator)
    log = filter_logs(stable, "Redeem")[0]

    assert (log.redeemer, log.user) == (funded_liquidator, borrower_position)
    assert (log.amount, log.eth) == (400 * ETH, eth)


def test_redeem_more_than_debt_reverts(stable, borrower_position, funded_liquidator, recipient):
    stable.deposit(value=10 * ETH, sender=recipient)
    stable.mint(POSITION_DEBT, sender=recipient)
    stable.transfer(funded_liquidator, POSITION_DEBT, sender=recipient)

    with boa.reverts(dev="[ministable] repay exceeds debt"):
        stable.redeem(borrower_position, POSITION_DEBT + 1, sender=funded_liquidator)


def test_redeem_unhealthy_position_reverts(
    stable, oracle, borrower_position, funded_liquidator
):
    """Positions under 150% are for liquidators, at a 10% bonus, not redeemers."""
    oracle.set_answer(to_feed_price(1400))
    assert stable.collat_ratio(borrower_position) < MIN_COLLAT_RATIO

    with boa.reverts(dev="[ministable] position unhealthy"):
        stable.redeem(borrower_position, ETH, sender=funded_liquidator)


def test_redeem_debt_free_position_reverts(stable, borrower, funded_liquidator):
    stable.deposit(value=ETH, sender=borrower)

    with boa.reverts(dev="[ministable] repay exceeds debt"):
        stable.redeem(borrower, ETH, sender=funded_liquidator)


def test_redeem_zero_reverts(stable, borrower_position, funded_liquidator):
    with boa.reverts(dev="[ministable] zero redeem"):
        stable.redeem(borrower_position, 0, sender=funded_liquidator)


def test_redeem_without_enough_musd_reverts(stable, borrower_position, liquidator):
    with boa.reverts(dev="[erc20] burn amount exceeds balance"):
        stable.redeem(borrower_position, ETH, sender=liquidator)


def test_redeem_with_stale_price_reverts(stable, borrower_position, funded_liquidator):
    boa.env.time_travel(seconds=stable.ORACLE_TIMEOUT() + 1)

    with boa.reverts(dev="[ministable] stale price"):
        stable.redeem(borrower_position, ETH, sender=funded_liquidator)


def test_redeem_own_position(stable, borrower_position):
    """Redeeming yourself is a repay that pays the fee to yourself."""
    stable.redeem(borrower_position, POSITION_DEBT, sender=borrower_position)

    assert stable.debt(borrower_position) == 0
    assert stable.balanceOf(borrower_position) == 0
