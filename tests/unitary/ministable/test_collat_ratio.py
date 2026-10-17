from tests.utils.constants import ETH, MAX_UINT256
from tests.utils.helpers import to_feed_price


def test_no_debt_is_max(stable, borrower):
    assert stable.collat_ratio(borrower) == MAX_UINT256


def test_collateral_without_debt_is_max(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    assert stable.collat_ratio(borrower) == MAX_UINT256


def test_ratio_value(stable, borrower_position):
    """$2000 of ETH backing $1000 of debt."""
    assert stable.collat_ratio(borrower_position) == 2 * 10**18


def test_ratio_scales_with_price(stable, oracle, borrower_position):
    oracle.set_answer(to_feed_price(3000))

    assert stable.collat_ratio(borrower_position) == 3 * 10**18


def test_ratio_scales_with_collateral(stable, borrower_position):
    stable.deposit(value=ETH, sender=borrower_position)

    assert stable.collat_ratio(borrower_position) == 4 * 10**18
