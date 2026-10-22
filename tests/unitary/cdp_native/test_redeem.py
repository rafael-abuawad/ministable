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


def test_redeem(cdp, borrower_position, funded_liquidator):
    """Money Flow: redeemer mUSD → burned, $1 of the borrower's ETH less 0.5% → redeemer."""
    borrower, redeemer = borrower_position, funded_liquidator
    redeemer_eth = boa.env.get_balance(redeemer)
    supply = cdp.totalSupply()
    amount = 400 * ETH
    eth = _redeemed_eth(amount)

    assert cdp.redeem(borrower, amount, sender=redeemer) == eth

    assert eth == 199 * ETH // 1000  # $400 at $2000, less 0.5%
    assert cdp.debt(borrower) == POSITION_DEBT - amount
    assert cdp.collateral(borrower) == POSITION_COLLATERAL - eth
    assert cdp.balanceOf(borrower) == POSITION_DEBT  # the borrower's mUSD is untouched
    assert cdp.balanceOf(redeemer) == POSITION_DEBT - amount
    assert cdp.totalSupply() == supply - amount
    assert boa.env.get_balance(redeemer) == redeemer_eth + eth


def test_fee_stays_with_borrower(cdp, borrower_position, funded_liquidator):
    """The borrower loses $400 of debt and $398 of ETH: they keep $2 of value."""
    amount = 400 * ETH
    eth = cdp.redeem(borrower_position, amount, sender=funded_liquidator)

    kept = amount - eth * 2000
    assert kept == amount * REDEMPTION_FEE // PRECISION


def test_redeem_raises_collat_ratio(cdp, borrower_position, funded_liquidator):
    ratio = cdp.collat_ratio(borrower_position)

    cdp.redeem(borrower_position, 400 * ETH, sender=funded_liquidator)

    assert cdp.collat_ratio(borrower_position) > ratio


def test_redeem_whole_debt(cdp, borrower_position, funded_liquidator):
    eth = cdp.redeem(borrower_position, POSITION_DEBT, sender=funded_liquidator)

    assert cdp.debt(borrower_position) == 0
    assert cdp.debt_shares(borrower_position) == 0
    assert cdp.collateral(borrower_position) == POSITION_COLLATERAL - eth


def test_redeem_emits_event(cdp, borrower_position, funded_liquidator):
    eth = cdp.redeem(borrower_position, 400 * ETH, sender=funded_liquidator)
    log = filter_logs(cdp, "Redeem")[0]

    assert (log.redeemer, log.user) == (funded_liquidator, borrower_position)
    assert (log.amount, log.paid) == (400 * ETH, eth)


def test_redeem_more_than_debt_reverts(cdp, borrower_position, funded_liquidator, recipient):
    cdp.deposit(value=10 * ETH, sender=recipient)
    cdp.mint(POSITION_DEBT, sender=recipient)
    cdp.transfer(funded_liquidator, POSITION_DEBT, sender=recipient)

    with boa.reverts(dev="[cdp] repay exceeds debt"):
        cdp.redeem(borrower_position, POSITION_DEBT + 1, sender=funded_liquidator)


def test_redeem_unhealthy_position_reverts(
    cdp, oracle, borrower_position, funded_liquidator
):
    """Positions under 150% are for liquidators, at a 10% bonus, not redeemers."""
    oracle.set_answer(to_feed_price(1400))
    assert cdp.collat_ratio(borrower_position) < MIN_COLLAT_RATIO

    with boa.reverts(dev="[cdp] position unhealthy"):
        cdp.redeem(borrower_position, ETH, sender=funded_liquidator)


def test_redeem_debt_free_position_reverts(cdp, borrower, funded_liquidator):
    cdp.deposit(value=ETH, sender=borrower)

    with boa.reverts(dev="[cdp] repay exceeds debt"):
        cdp.redeem(borrower, ETH, sender=funded_liquidator)


def test_redeem_zero_reverts(cdp, borrower_position, funded_liquidator):
    with boa.reverts(dev="[cdp] zero redeem"):
        cdp.redeem(borrower_position, 0, sender=funded_liquidator)


def test_redeem_without_enough_musd_reverts(cdp, borrower_position, liquidator):
    with boa.reverts(dev="[erc20] burn amount exceeds balance"):
        cdp.redeem(borrower_position, ETH, sender=liquidator)


def test_redeem_with_stale_price_reverts(cdp, borrower_position, funded_liquidator):
    boa.env.time_travel(seconds=cdp.ORACLE_TIMEOUT() + 1)

    with boa.reverts(dev="[cdp] stale price"):
        cdp.redeem(borrower_position, ETH, sender=funded_liquidator)


def test_redeem_own_position(cdp, borrower_position):
    """Redeeming yourself is a repay that pays the fee to yourself."""
    cdp.redeem(borrower_position, POSITION_DEBT, sender=borrower_position)

    assert cdp.debt(borrower_position) == 0
    assert cdp.balanceOf(borrower_position) == 0
