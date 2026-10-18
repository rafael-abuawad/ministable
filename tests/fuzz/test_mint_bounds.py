import boa
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tests.utils.constants import ETH, MIN_COLLAT_RATIO
from tests.utils.helpers import max_mintable

collateral_st = st.integers(min_value=1, max_value=10_000 * ETH)
# $1 to $1M with 8-decimal precision.
feed_price_st = st.integers(min_value=10**8, max_value=10**6 * 10**8)


@settings(max_examples=200, deadline=None)
@given(collateral=collateral_st, feed_price=feed_price_st)
def test_max_mint_is_exact_bound(stable, oracle, borrower, collateral, feed_price):
    """`max_mintable` succeeds and one wei more reverts, for any collateral and price."""
    limit = max_mintable(collateral, feed_price)
    assume(limit > 0)

    with boa.env.anchor():
        boa.env.set_balance(borrower, collateral)
        oracle.set_answer(feed_price)
        stable.deposit(value=collateral, sender=borrower)

        with boa.reverts(dev="[ministable] undercollateralized"):
            stable.mint(limit + 1, sender=borrower)

        stable.mint(limit, sender=borrower)
        assert stable.collat_ratio(borrower) >= MIN_COLLAT_RATIO


@settings(max_examples=200, deadline=None)
@given(
    collateral=collateral_st,
    feed_price=feed_price_st,
    fraction=st.integers(min_value=0, max_value=100),
)
def test_max_withdraw_is_exact_bound(
    stable, oracle, borrower, collateral, feed_price, fraction
):
    """After minting, withdrawing past the 150% line always reverts."""
    debt = max_mintable(collateral, feed_price) * fraction // 100
    assume(debt > 0)

    with boa.env.anchor():
        boa.env.set_balance(borrower, collateral)
        oracle.set_answer(feed_price)
        stable.deposit(value=collateral, sender=borrower)
        stable.mint(debt, sender=borrower)

        # Smallest collateral that still backs `debt`.
        required = next(
            c
            for c in _candidates(debt, feed_price)
            if max_mintable(c, feed_price) >= debt
        )
        free = collateral - required

        with boa.reverts(dev="[ministable] undercollateralized"):
            stable.withdraw(free + 1, sender=borrower)

        if free > 0:
            stable.withdraw(free, sender=borrower)
        assert stable.collat_ratio(borrower) >= MIN_COLLAT_RATIO


def _candidates(debt: int, feed_price: int):
    # Analytical lower bound, then step up past integer-division rounding.
    c = debt * MIN_COLLAT_RATIO // (feed_price * 10**10)
    while True:
        yield c
        c += 1
