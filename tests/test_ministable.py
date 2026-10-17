import boa

ETH = 10**18
MAX_MINT_PER_ETH = 2000 * ETH * 10**18 // (15 * 10**17)  # 1333.33 mUSD at $2000


def test_metadata(stable, oracle):
    assert stable.name() == "ministable"
    assert stable.symbol() == "mUSD"
    assert stable.decimals() == 18
    assert stable.MIN_COLLAT_RATIO() == 15 * 10**17
    assert stable.ORACLE() == oracle.address


# Deposits


def test_deposit(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
    assert stable.collateral(user) == ETH
    assert boa.env.get_balance(stable.address) == ETH


def test_deposit_via_plain_transfer(stable, user):
    boa.env.raw_call(stable.address, sender=user, value=ETH)
    assert stable.collateral(user) == ETH
    assert boa.env.get_balance(stable.address) == ETH


def test_zero_deposit_reverts(stable, user):
    with boa.env.prank(user):
        with boa.reverts("ministable: zero deposit"):
            stable.deposit()


# Mint


def test_mint_up_to_limit(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(MAX_MINT_PER_ETH)
    assert stable.balanceOf(user) == MAX_MINT_PER_ETH
    assert stable.debt(user) == MAX_MINT_PER_ETH
    assert stable.totalSupply() == MAX_MINT_PER_ETH
    assert stable.collat_ratio(user) >= stable.MIN_COLLAT_RATIO()


def test_mint_above_limit_reverts(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        with boa.reverts("ministable: undercollateralized"):
            stable.mint(MAX_MINT_PER_ETH + 10**18)


def test_mint_without_collateral_reverts(stable, user):
    with boa.env.prank(user):
        with boa.reverts("ministable: undercollateralized"):
            stable.mint(1)


# Burn


def test_burn(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(1000 * ETH)
        stable.burn(400 * ETH)
    assert stable.debt(user) == 600 * ETH
    assert stable.balanceOf(user) == 600 * ETH
    assert stable.totalSupply() == 600 * ETH


def test_burn_more_than_debt_reverts(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(100 * ETH)
        with boa.reverts():
            stable.burn(101 * ETH)


# Withdraw


def test_withdraw_without_debt(stable, user):
    start = boa.env.get_balance(user)
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.withdraw(ETH)
    assert stable.collateral(user) == 0
    assert boa.env.get_balance(user) == start


def test_withdraw_keeping_ratio(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=2 * ETH)
        stable.mint(1000 * ETH)  # needs 0.75 ETH at $2000
        stable.withdraw(ETH)
    assert stable.collateral(user) == ETH
    assert stable.collat_ratio(user) == 2 * 10**18


def test_withdraw_breaking_ratio_reverts(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(1000 * ETH)
        with boa.reverts("ministable: undercollateralized"):
            stable.withdraw(ETH // 2)


def test_withdraw_more_than_collateral_reverts(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        with boa.reverts():
            stable.withdraw(ETH + 1)


# Liquidate


def _open_position(stable, user, liquidator):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(1000 * ETH)
    # Liquidator mints their own mUSD to cover the debt.
    with boa.env.prank(liquidator):
        stable.deposit(value=10 * ETH)
        stable.mint(1000 * ETH)


def test_liquidate_healthy_reverts(stable, user, liquidator):
    _open_position(stable, user, liquidator)
    with boa.env.prank(liquidator):
        with boa.reverts("ministable: position healthy"):
            stable.liquidate(user)


def test_liquidate_after_price_drop(stable, oracle, user, liquidator):
    _open_position(stable, user, liquidator)
    oracle.set_answer(1400 * 10**8)  # 1 ETH = $1400 < 1.5 * $1000
    assert stable.collat_ratio(user) < stable.MIN_COLLAT_RATIO()

    eth_before = boa.env.get_balance(liquidator)
    with boa.env.prank(liquidator):
        stable.liquidate(user)

    assert stable.debt(user) == 0
    assert stable.collateral(user) == 0
    assert stable.balanceOf(liquidator) == 0
    assert stable.balanceOf(user) == 1000 * ETH  # user keeps the mUSD they minted
    assert stable.totalSupply() == 1000 * ETH
    assert boa.env.get_balance(liquidator) == eth_before + ETH


def test_liquidate_without_enough_musd_reverts(stable, oracle, user, liquidator):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(1000 * ETH)
    oracle.set_answer(1400 * 10**8)
    with boa.env.prank(liquidator):
        with boa.reverts():
            stable.liquidate(user)


# Collateral ratio and oracle


def test_collat_ratio_no_debt_is_max(stable, user):
    assert stable.collat_ratio(user) == 2**256 - 1


def test_collat_ratio_value(stable, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
        stable.mint(1000 * ETH)
    assert stable.collat_ratio(user) == 2 * 10**18  # $2000 / $1000


def test_stale_price_reverts(stable, oracle, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
    boa.env.time_travel(seconds=stable.ORACLE_TIMEOUT() + 1)
    with boa.env.prank(user):
        with boa.reverts("ministable: stale price"):
            stable.mint(1)


def test_non_positive_price_reverts(stable, oracle, user):
    with boa.env.prank(user):
        stable.deposit(value=ETH)
    oracle.set_answer(0)
    with boa.env.prank(user):
        with boa.reverts("ministable: invalid price"):
            stable.mint(1)
    oracle.set_answer(-1)
    with boa.env.prank(user):
        with boa.reverts("ministable: invalid price"):
            stable.mint(1)
