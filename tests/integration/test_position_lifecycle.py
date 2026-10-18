import boa

from tests.utils.constants import ETH, MIN_COLLAT_RATIO
from tests.utils.helpers import max_mintable, to_feed_price


def test_open_and_close_position(stable, borrower):
    """Money Flow: ETH in → mUSD out → mUSD burned → ETH back. Borrower ends whole."""
    borrower_eth = boa.env.get_balance(borrower)

    # ================= Open =================
    stable.deposit(value=2 * ETH, sender=borrower)
    stable.mint(2000 * ETH, sender=borrower)
    assert stable.collat_ratio(borrower) == 2 * 10**18

    # ================= Close =================
    stable.burn(2000 * ETH, sender=borrower)
    stable.withdraw(2 * ETH, sender=borrower)

    # ================= Verify =================
    assert stable.collateral(borrower) == 0
    assert stable.debt(borrower) == 0
    assert stable.totalSupply() == 0
    assert boa.env.get_balance(stable.address) == 0
    assert boa.env.get_balance(borrower) == borrower_eth


def test_rising_price_frees_collateral(stable, oracle, borrower):
    stable.deposit(value=2 * ETH, sender=borrower)
    stable.mint(max_mintable(2 * ETH, to_feed_price(2000)), sender=borrower)

    # At $2000 the position is maxed out, so nothing can be withdrawn.
    with boa.reverts(dev="[ministable] undercollateralized"):
        stable.withdraw(1, sender=borrower)

    # At $4000 half the collateral covers the same debt.
    oracle.set_answer(to_feed_price(4000))
    stable.withdraw(ETH, sender=borrower)

    assert stable.collateral(borrower) == ETH
    assert stable.collat_ratio(borrower) >= MIN_COLLAT_RATIO


def test_liquidation_with_purchased_musd(
    stable, oracle, borrower, liquidator, recipient
):
    """Liquidator buys mUSD from a third party, then liquidates the borrower."""
    # ================= Setup =================
    stable.deposit(value=ETH, sender=borrower)
    stable.mint(1000 * ETH, sender=borrower)

    stable.deposit(value=5 * ETH, sender=recipient)
    stable.mint(1000 * ETH, sender=recipient)
    stable.transfer(liquidator, 1000 * ETH, sender=recipient)  # off-chain purchase

    liquidator_eth = boa.env.get_balance(liquidator)

    # ================= Execute =================
    oracle.set_answer(to_feed_price(1200))
    stable.liquidate(borrower, sender=liquidator)

    # ================= Verify =================
    # Liquidator paid 1000 mUSD and received 1 ETH ($1200).
    assert boa.env.get_balance(liquidator) == liquidator_eth + ETH
    assert stable.balanceOf(liquidator) == 0

    # The seller's position is unaffected and still healthy.
    assert stable.debt(recipient) == 1000 * ETH
    assert stable.collat_ratio(recipient) >= MIN_COLLAT_RATIO

    # Outstanding supply equals outstanding debt; ETH held equals collateral.
    assert stable.totalSupply() == stable.debt(borrower) + stable.debt(recipient)
    assert boa.env.get_balance(stable.address) == stable.collateral(recipient)


def test_partial_repay_rescues_position(stable, oracle, borrower, liquidator):
    """Burning debt after a price drop lifts the position back above 150%."""
    stable.deposit(value=ETH, sender=borrower)
    stable.mint(1000 * ETH, sender=borrower)
    oracle.set_answer(to_feed_price(1400))
    assert stable.collat_ratio(borrower) < MIN_COLLAT_RATIO

    stable.burn(200 * ETH, sender=borrower)  # $1400 / $800 = 175%

    assert stable.collat_ratio(borrower) >= MIN_COLLAT_RATIO
    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower, sender=liquidator)


def test_topping_up_collateral_rescues_position(stable, oracle, borrower, liquidator):
    stable.deposit(value=ETH, sender=borrower)
    stable.mint(1000 * ETH, sender=borrower)
    oracle.set_answer(to_feed_price(1400))

    stable.deposit(value=ETH, sender=borrower)  # $2800 / $1000 = 280%

    assert stable.collat_ratio(borrower) == 28 * 10**17
    with boa.reverts(dev="[ministable] position healthy"):
        stable.liquidate(borrower, sender=liquidator)
