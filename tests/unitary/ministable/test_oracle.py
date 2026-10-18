import boa

from tests.utils.constants import ETH, ORACLE_TIMEOUT
from tests.utils.helpers import to_feed_price


def test_mock_reports_8_decimals(oracle):
    assert oracle.decimals() == 8


def test_price_at_timeout_is_fresh(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)
    boa.env.time_travel(seconds=ORACLE_TIMEOUT)

    stable.mint(1, sender=borrower)

    assert stable.debt(borrower) == 1


def test_stale_price_reverts(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)
    boa.env.time_travel(seconds=ORACLE_TIMEOUT + 1)

    with boa.reverts(dev="[ministable] stale price"):
        stable.mint(1, sender=borrower)


def test_refreshed_price_unblocks(stable, oracle, borrower):
    stable.deposit(value=ETH, sender=borrower)
    boa.env.time_travel(seconds=ORACLE_TIMEOUT + 1)
    oracle.set_answer(to_feed_price(2000))

    stable.mint(1, sender=borrower)


def test_zero_price_reverts(stable, oracle, borrower):
    stable.deposit(value=ETH, sender=borrower)
    oracle.set_answer(0)

    with boa.reverts(dev="[ministable] invalid price"):
        stable.mint(1, sender=borrower)


def test_negative_price_reverts(stable, oracle, borrower):
    stable.deposit(value=ETH, sender=borrower)
    oracle.set_answer(-1)

    with boa.reverts(dev="[ministable] invalid price"):
        stable.mint(1, sender=borrower)


def test_collat_ratio_view_reverts_on_bad_price(stable, oracle, borrower_position):
    oracle.set_answer(0)

    with boa.reverts(dev="[ministable] invalid price"):
        stable.collat_ratio(borrower_position)
