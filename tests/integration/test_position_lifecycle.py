import boa

from tests.utils.constants import ETH, MAX_UINT256, MIN_COLLAT_RATIO
from tests.utils.helpers import liquidation, max_mintable, to_feed_price


def test_open_and_close_position(cdp, borrower):
    """Money Flow: ETH in → mUSD out → mUSD burned → ETH back. Borrower ends whole."""
    borrower_eth = boa.env.get_balance(borrower)

    # ================= Open =================
    cdp.deposit(value=2 * ETH, sender=borrower)
    cdp.mint(2000 * ETH, sender=borrower)
    assert cdp.collat_ratio(borrower) == 2 * 10**18

    # ================= Close =================
    cdp.burn(2000 * ETH, sender=borrower)
    cdp.withdraw(2 * ETH, sender=borrower)

    # ================= Verify =================
    assert cdp.collateral(borrower) == 0
    assert cdp.debt(borrower) == 0
    assert cdp.totalSupply() == 0
    assert boa.env.get_balance(cdp.address) == 0
    assert boa.env.get_balance(borrower) == borrower_eth


def test_rising_price_frees_collateral(cdp, oracle, borrower):
    cdp.deposit(value=2 * ETH, sender=borrower)
    cdp.mint(max_mintable(2 * ETH, to_feed_price(2000)), sender=borrower)

    # At $2000 the position is maxed out, so nothing can be withdrawn.
    with boa.reverts(dev="[cdp_native] undercollateralized"):
        cdp.withdraw(1, sender=borrower)

    # At $4000 half the collateral covers the same debt.
    oracle.set_answer(to_feed_price(4000))
    cdp.withdraw(ETH, sender=borrower)

    assert cdp.collateral(borrower) == ETH
    assert cdp.collat_ratio(borrower) >= MIN_COLLAT_RATIO


def test_liquidation_with_purchased_musd(
    cdp, oracle, borrower, liquidator, recipient
):
    """Liquidator buys mUSD from a third party, then liquidates the borrower
    back to 150%. The borrower keeps the rest of their ETH."""
    # ================= Setup =================
    cdp.deposit(value=ETH, sender=borrower)
    cdp.mint(1000 * ETH, sender=borrower)

    cdp.deposit(value=5 * ETH, sender=recipient)
    cdp.mint(1000 * ETH, sender=recipient)
    cdp.transfer(liquidator, 1000 * ETH, sender=recipient)  # off-chain purchase

    liquidator_eth = boa.env.get_balance(liquidator)

    # ================= Execute =================
    oracle.set_answer(to_feed_price(1200))
    cdp.liquidate(borrower, MAX_UINT256, sender=liquidator)

    # ================= Verify =================
    # At $1200 (120%) the liquidator repays 750 mUSD for $825 of ETH,
    # leaving the borrower with 250 mUSD of debt against $375 of ETH.
    # The 10 wei on top is `liquidate`'s rounding margin.
    repaid, seized, _ = liquidation(ETH, 1000 * ETH, to_feed_price(1200), MAX_UINT256)
    assert repaid == 750 * ETH + 10
    assert boa.env.get_balance(liquidator) == liquidator_eth + seized
    assert cdp.balanceOf(liquidator) == 1000 * ETH - repaid
    assert cdp.debt(borrower) == 1000 * ETH - repaid
    assert cdp.collateral(borrower) == ETH - seized
    assert cdp.collat_ratio(borrower) >= MIN_COLLAT_RATIO

    # The seller's position is unaffected and still healthy.
    assert cdp.debt(recipient) == 1000 * ETH
    assert cdp.collat_ratio(recipient) >= MIN_COLLAT_RATIO

    # Outstanding supply equals outstanding debt; ETH held equals collateral.
    assert cdp.totalSupply() == cdp.debt(borrower) + cdp.debt(recipient)
    assert boa.env.get_balance(cdp.address) == (
        cdp.collateral(recipient) + cdp.collateral(borrower)
    )


def test_partial_repay_rescues_position(cdp, oracle, borrower, liquidator):
    """Burning debt after a price drop lifts the position back above 150%."""
    cdp.deposit(value=ETH, sender=borrower)
    cdp.mint(1000 * ETH, sender=borrower)
    oracle.set_answer(to_feed_price(1400))
    assert cdp.collat_ratio(borrower) < MIN_COLLAT_RATIO

    cdp.burn(200 * ETH, sender=borrower)  # $1400 / $800 = 175%

    assert cdp.collat_ratio(borrower) >= MIN_COLLAT_RATIO
    with boa.reverts(dev="[cdp_native] position healthy"):
        cdp.liquidate(borrower, MAX_UINT256, sender=liquidator)


def test_topping_up_collateral_rescues_position(cdp, oracle, borrower, liquidator):
    cdp.deposit(value=ETH, sender=borrower)
    cdp.mint(1000 * ETH, sender=borrower)
    oracle.set_answer(to_feed_price(1400))

    cdp.deposit(value=ETH, sender=borrower)  # $2800 / $1000 = 280%

    assert cdp.collat_ratio(borrower) == 28 * 10**17
    with boa.reverts(dev="[cdp_native] position healthy"):
        cdp.liquidate(borrower, MAX_UINT256, sender=liquidator)
