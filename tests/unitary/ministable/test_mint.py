import boa

from tests.utils.constants import ETH, MAX_MINT_PER_ETH, MIN_COLLAT_RATIO
from tests.utils.helpers import filter_logs, to_feed_price


def test_mint_issues_debt_and_tokens(stable, borrower):
    """Money Flow: new mUSD → borrower, debt recorded."""
    amount = 1000 * ETH
    stable.deposit(value=ETH, sender=borrower)

    # ================= Execute =================
    stable.mint(amount, sender=borrower)

    # ================= Verify state =================
    assert stable.debt(borrower) == amount
    assert stable.balanceOf(borrower) == amount
    assert stable.totalSupply() == amount


def test_mint_emits_events(stable, borrower):
    amount = 1000 * ETH
    stable.deposit(value=ETH, sender=borrower)

    stable.mint(amount, sender=borrower)

    mint_logs = filter_logs(stable, "Mint")
    assert len(mint_logs) == 1
    assert mint_logs[0].user == borrower
    assert mint_logs[0].amount == amount

    transfer_logs = filter_logs(stable, "Transfer")
    assert len(transfer_logs) == 1
    assert transfer_logs[0].sender == boa.eval("empty(address)")
    assert transfer_logs[0].receiver == borrower
    assert transfer_logs[0].value == amount


def test_mint_up_to_limit(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    stable.mint(MAX_MINT_PER_ETH, sender=borrower)

    assert stable.debt(borrower) == MAX_MINT_PER_ETH
    assert stable.collat_ratio(borrower) >= MIN_COLLAT_RATIO


def test_mint_one_wei_above_limit_reverts(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    with boa.reverts("ministable: undercollateralized"):
        stable.mint(MAX_MINT_PER_ETH + 1, sender=borrower)


def test_mint_in_steps_hits_same_limit(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)
    stable.mint(MAX_MINT_PER_ETH // 2, sender=borrower)
    stable.mint(MAX_MINT_PER_ETH - MAX_MINT_PER_ETH // 2, sender=borrower)

    with boa.reverts("ministable: undercollateralized"):
        stable.mint(1, sender=borrower)


def test_mint_without_collateral_reverts(stable, borrower):
    with boa.reverts("ministable: undercollateralized"):
        stable.mint(1, sender=borrower)


def test_mint_limit_tracks_price(stable, oracle, borrower):
    stable.deposit(value=ETH, sender=borrower)
    stable.mint(MAX_MINT_PER_ETH, sender=borrower)

    oracle.set_answer(to_feed_price(4000))

    stable.mint(MAX_MINT_PER_ETH, sender=borrower)
    assert stable.debt(borrower) == 2 * MAX_MINT_PER_ETH


def test_mint_does_not_change_collateral(stable, borrower):
    stable.deposit(value=ETH, sender=borrower)

    stable.mint(1000 * ETH, sender=borrower)

    assert stable.collateral(borrower) == ETH
    assert boa.env.get_balance(stable.address) == ETH
