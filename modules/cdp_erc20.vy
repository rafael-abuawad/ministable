# pragma version ~=0.4.3
# pragma nonreentrancy on
"""
@title CDP Engine Backed by an ERC-20 Token
@custom:contract-name cdp_erc20
@notice Users lock an ERC-20 collateral token (e.g. USDC,
        USDT, WETH) via `deposit` and mint the stablecoin
        against it at a minimum 150% collateral ratio. Debt
        accrues a fixed stability fee, minted to the
        protocol's surplus. Positions below 150% can be
        liquidated back to 150%: the liquidator repays debt
        and receives 110% of it in collateral. Debt that a
        position's collateral cannot cover becomes bad debt,
        which the surplus and reserve absorb. Anyone can
        redeem the stablecoin for $1 of collateral from a
        healthy position.

        The collateral token may have up to 18 decimals and
        may omit the `bool` return value on `transfer` and
        `transferFrom` (as USDT does). Deposits credit the
        balance the contract actually received, so tokens
        that charge a fee on transfer are accounted for.
        Rebasing tokens are not supported: a negative rebase
        would leave the contract holding less than it owes.
@license GNU Affero General Public License v3.0 only
@author rafael-abuawad
"""


# @dev We import the `IERC20` interface, which is
# a built-in interface of the Vyper compiler, for
# the collateral token.
from ethereum.ercs import IERC20


# @dev We import the `IERC20Detailed` interface, which
# is a built-in interface of the Vyper compiler, to read
# the collateral token's decimals.
from ethereum.ercs import IERC20Detailed


# @dev We import the `IAggregatorV3` interface
# for the Chainlink collateral / USD price feed.
from src.interfaces import IAggregatorV3


# @dev We import and use the `erc20` module,
# which tracks the stablecoin minted against
# the collateral.
from modules import erc20
uses: erc20


# @dev Minimum collateral ratio, 1e18-scaled (150%).
MIN_COLLAT_RATIO: public(constant(uint256)) = 15 * 10**17


# @dev Time the L2 sequencer must have been back up
# before prices are trusted again, in seconds.
SEQUENCER_GRACE_PERIOD: public(constant(uint256)) = 3600


# @dev Collateral a liquidator receives per mUSD repaid, valued
# at the oracle price, 1e18-scaled (110%: a 10% bonus).
LIQUIDATION_PENALTY: public(constant(uint256)) = 11 * 10**17


# @dev Share of a redemption's collateral left with the borrower
# whose position is redeemed, 1e18-scaled (0.5%).
REDEMPTION_FEE: public(constant(uint256)) = 5 * 10**15


# @dev Largest allowed stability fee: 10% a year, as a
# 1e18-scaled per-second rate.
MAX_STABILITY_FEE: public(constant(uint256)) = 10**17 // (365 * 86400)


# @dev Constant to calculate the precision.
PRECISION: constant(uint256) = 10**18


# @dev The ERC-20 token locked as collateral.
COLLATERAL: public(immutable(IERC20))


# @dev The collateral token / USD price feed.
ORACLE: public(immutable(IAggregatorV3))


# @dev Maximum age of an oracle answer, in seconds.
# Set per network at deployment: the feed's heartbeat
# plus a buffer.
ORACLE_TIMEOUT: public(immutable(uint256))


# @dev Scales an oracle answer to the 1e18-scaled USD
# value of 1e18 base units of the collateral token, so
# that `amount * _price() // 1e18` is the USD value of
# `amount` base units at 18 decimals, whatever the
# decimals of the token and the feed.
PRICE_SCALE: immutable(uint256)


# @dev The Chainlink L2 sequencer uptime feed, or
# `empty(address)` on networks without a sequencer.
SEQUENCER_UPTIME_FEED: public(immutable(IAggregatorV3))


# @dev Interest charged on debt, as a 1e18-scaled
# per-second rate. Fixed at deployment.
STABILITY_FEE: public(immutable(uint256))


# @dev Returns the collateral (in token base units)
# locked by an `address`.
collateral: public(HashMap[address, uint256])


# @dev Returns the normalised debt of an `address`.
# Its debt in mUSD is `debt_shares * rate_index / 1e18`.
debt_shares: public(HashMap[address, uint256])


# @dev Returns the sum of all `debt_shares`.
total_debt_shares: public(uint256)


# @dev Returns the 1e18-scaled interest index. It starts
# at 1e18 and grows by `STABILITY_FEE` every second.
rate_index: public(uint256)


# @dev Returns when `rate_index` was last updated.
last_accrual: public(uint256)


# @dev Returns the collateral (in token base units)
# paid for surplus mUSD.
reserve: public(uint256)


# @dev Returns the mUSD in circulation that no position
# owes: debt written off when a position's collateral could not
# cover it, not yet absorbed by the surplus or reserve.
bad_debt: public(uint256)


# @dev Emitted when `user` locks `amount` base
# units of the collateral token.
event Deposit:
    user: indexed(address)
    amount: uint256


# @dev Emitted when `user` withdraws `amount`
# base units of collateral.
event Withdraw:
    user: indexed(address)
    amount: uint256


# @dev Emitted when `user` mints `amount` mUSD
# against their collateral.
event Mint:
    user: indexed(address)
    amount: uint256


# @dev Emitted when `user` burns `amount` mUSD
# to repay their debt.
event Burn:
    user: indexed(address)
    amount: uint256


# @dev Emitted when `amount` mUSD of interest is
# minted to the surplus.
event Accrue:
    amount: uint256


# @dev Emitted when `buyer` pays `paid` base units of
# collateral for `amount` mUSD from the surplus.
event BuySurplus:
    buyer: indexed(address)
    paid: uint256
    amount: uint256


# @dev Emitted when `liquidator` burns `repaid` mUSD
# of `user`'s debt and receives `seized` base units of
# their collateral. `written_off` is debt the collateral
# could not cover, moved to `bad_debt`.
event Liquidate:
    liquidator: indexed(address)
    user: indexed(address)
    repaid: uint256
    seized: uint256
    written_off: uint256


# @dev Emitted when `redeemer` burns `amount` mUSD of
# `user`'s debt and receives `paid` base units of their
# collateral.
event Redeem:
    redeemer: indexed(address)
    user: indexed(address)
    amount: uint256
    paid: uint256


# @dev Emitted when `amount` mUSD of surplus is burned
# against bad debt.
event Settle:
    amount: uint256


# @dev Emitted when `caller` burns `amount` mUSD of
# bad debt and receives `paid` base units of collateral
# from the reserve.
event CoverBadDebt:
    caller: indexed(address)
    amount: uint256
    paid: uint256


@deploy
def __init__(
    collateral_: IERC20,
    oracle: IAggregatorV3,
    oracle_timeout_: uint256,
    sequencer_uptime_feed_: IAggregatorV3,
    stability_fee_: uint256,
):
    # @dev The stablecoin cannot back itself.
    assert collateral_.address != self # dev: [cdp_erc20] invalid collateral
    collateral_decimals: uint8 = staticcall IERC20Detailed(collateral_.address).decimals()
    assert collateral_decimals <= 18 # dev: [cdp_erc20] unsupported collateral decimals
    assert oracle_timeout_ > 0 # dev: [cdp_erc20] zero oracle timeout
    oracle_decimals: uint8 = staticcall oracle.decimals()
    assert oracle_decimals <= 18 # dev: [cdp_erc20] unsupported oracle decimals
    COLLATERAL = collateral_
    ORACLE = oracle
    ORACLE_TIMEOUT = oracle_timeout_
    PRICE_SCALE = 10 ** (36 - convert(oracle_decimals, uint256) - convert(collateral_decimals, uint256))
    SEQUENCER_UPTIME_FEED = sequencer_uptime_feed_
    assert stability_fee_ <= MAX_STABILITY_FEE # dev: [cdp_erc20] stability fee too high
    STABILITY_FEE = stability_fee_
    self.rate_index = PRECISION
    self.last_accrual = block.timestamp


# @dev Pulls `amount` base units of the collateral token from
# the caller, who must have approved this contract, and locks
# what arrives as their collateral. Returns the amount credited.
@external
def deposit(amount: uint256) -> uint256:
    received: uint256 = self._pull(msg.sender, amount)
    assert received > 0 # dev: [cdp_erc20] zero deposit
    self.collateral[msg.sender] += received
    log Deposit(user=msg.sender, amount=received)
    return received


# @dev Mints `amount` mUSD against the caller's collateral.
@external
def mint(amount: uint256):
    self._accrue()
    shares: uint256 = self._shares_up(amount)
    self.debt_shares[msg.sender] += shares
    self.total_debt_shares += shares
    assert self._collat_ratio(msg.sender) >= MIN_COLLAT_RATIO # dev: [cdp_erc20] undercollateralized
    erc20._mint(msg.sender, amount)
    log Mint(user=msg.sender, amount=amount)


# @dev Burns `amount` mUSD to repay the caller's debt.
@external
def burn(amount: uint256):
    self._accrue()
    self._repay(msg.sender, amount)
    erc20._burn(msg.sender, amount)
    log Burn(user=msg.sender, amount=amount)


# @dev Withdraws `amount` base units of the caller's collateral.
@external
def withdraw(amount: uint256):
    self._accrue()
    self.collateral[msg.sender] -= amount
    assert self._collat_ratio(msg.sender) >= MIN_COLLAT_RATIO # dev: [cdp_erc20] undercollateralized
    log Withdraw(user=msg.sender, amount=amount)
    self._push(msg.sender, amount)


# @dev Liquidates an undercollateralized `user`. The caller
# repays up to `max_repay` mUSD of their debt and receives
# `LIQUIDATION_PENALTY` (110%) of it in collateral. Returns the
# mUSD repaid.
#
# If the collateral covers 110% of the debt, the caller
# repays only what brings the position back to 150%, and
# the borrower keeps the rest of their collateral. Otherwise the
# caller repays what the collateral covers at 110%, takes
# all of it, and the rest of the debt becomes bad debt.
@external
def liquidate(user: address, max_repay: uint256) -> uint256:
    self._accrue()
    assert self._collat_ratio(user) < MIN_COLLAT_RATIO # dev: [cdp_erc20] position healthy
    p: uint256 = self._price()
    d: uint256 = self._debt(user)
    c: uint256 = self.collateral[user]
    # @dev USD value of the collateral, 1e36-scaled. Floored
    # as in `_collat_ratio`, so `needed` below is positive.
    value: uint256 = c * p // PRECISION * PRECISION

    repay: uint256 = 0
    seized: uint256 = 0
    written_off: uint256 = 0
    if value >= LIQUIDATION_PENALTY * d:
        # @dev Solve (value - 1.1x) / (d - x) = 1.5 for x,
        # rounding up so the position ends at or above 150%.
        # The margins cover rounding after the repay: the
        # collateral value floors by up to 1 wei, and the debt
        # left, whose removed shares round down, exceeds `d - x`
        # by up to `rate_index / 1e18 + 1` wei.
        debt_margin: uint256 = self.rate_index // PRECISION + 1
        needed: uint256 = MIN_COLLAT_RATIO * (d + debt_margin) - value + PRECISION
        step: uint256 = MIN_COLLAT_RATIO - LIQUIDATION_PENALTY
        repay = min(min((needed + step - 1) // step, d), max_repay)
        assert repay > 0 # dev: [cdp_erc20] zero repay
        seized = min(repay * LIQUIDATION_PENALTY // p, c)
        self._repay(user, repay)
    else:
        repay = value // LIQUIDATION_PENALTY
        assert max_repay >= repay # dev: [cdp_erc20] repay too small
        seized = c
        written_off = d - repay
        self.total_debt_shares -= self.debt_shares[user]
        self.debt_shares[user] = 0
        self.bad_debt += written_off

    self.collateral[user] -= seized
    erc20._burn(msg.sender, repay)
    log Liquidate(liquidator=msg.sender, user=user, repaid=repay, seized=seized, written_off=written_off)
    self._settle()
    self._push(msg.sender, seized)
    return repay


# @dev Swaps `amount` of the caller's mUSD for $1 of collateral
# per mUSD from `user`'s position, at the oracle price,
# less `REDEMPTION_FEE`, which stays with the borrower.
# This puts a hard floor under the peg. Only healthy
# positions can be redeemed; the caller picks which.
# Returns the collateral paid, in base units.
@external
def redeem(user: address, amount: uint256) -> uint256:
    self._accrue()
    assert amount > 0 # dev: [cdp_erc20] zero redeem
    assert self._collat_ratio(user) >= MIN_COLLAT_RATIO # dev: [cdp_erc20] position unhealthy
    paid: uint256 = amount * (PRECISION - REDEMPTION_FEE) // self._price()
    self._repay(user, amount)
    self.collateral[user] -= paid
    erc20._burn(msg.sender, amount)
    log Redeem(redeemer=msg.sender, user=user, amount=amount, paid=paid)
    self._push(msg.sender, paid)
    return paid


# @dev Burns `amount` mUSD of bad debt from the caller and
# pays them its value in collateral from the reserve, at the
# oracle price.
@external
def cover_bad_debt(amount: uint256) -> uint256:
    self._accrue()
    assert amount > 0 # dev: [cdp_erc20] zero cover
    assert amount <= self.bad_debt # dev: [cdp_erc20] cover exceeds bad debt
    paid: uint256 = amount * PRECISION // self._price()
    assert paid <= self.reserve # dev: [cdp_erc20] not enough reserve
    self.bad_debt -= amount
    self.reserve -= paid
    erc20._burn(msg.sender, amount)
    log CoverBadDebt(caller=msg.sender, amount=amount, paid=paid)
    self._push(msg.sender, paid)
    return paid


# @dev Sells surplus mUSD for `amount` base units of the
# collateral token, pulled from the caller at the oracle
# price. Interest is minted to the surplus, so this is how
# it reaches borrowers who need it to repay. The collateral
# paid is kept in the reserve.
@external
def buy_surplus(amount: uint256) -> uint256:
    self._accrue()
    received: uint256 = self._pull(msg.sender, amount)
    bought: uint256 = received * self._price() // PRECISION
    assert bought > 0 # dev: [cdp_erc20] zero purchase
    assert bought <= erc20.balanceOf[self] # dev: [cdp_erc20] not enough surplus
    self.reserve += received
    erc20._transfer(self, msg.sender, bought)
    log BuySurplus(buyer=msg.sender, paid=received, amount=bought)
    return bought


# @dev Returns the mUSD debt of `user`, interest included.
@view
@external
def debt(user: address) -> uint256:
    return self._debt(user)


# @dev Returns the mUSD held by the protocol: interest not
# yet sold or spent on bad debt.
@view
@external
def surplus() -> uint256:
    return erc20.balanceOf[self]


# @dev Returns the 1e18-scaled collateral ratio of `user`.
@view
@external
def collat_ratio(user: address) -> uint256:
    return self._collat_ratio(user)


# @dev Pulls `amount` of the collateral token from `owner` and
# returns what this contract actually received, which is less
# than `amount` for tokens that charge a fee on transfer.
@internal
def _pull(owner: address, amount: uint256) -> uint256:
    before: uint256 = staticcall COLLATERAL.balanceOf(self)
    assert extcall COLLATERAL.transferFrom(owner, self, amount, default_return_value=True) # dev: [cdp_erc20] transfer failed
    return staticcall COLLATERAL.balanceOf(self) - before


# @dev Sends `amount` of the collateral token to `to`.
@internal
def _push(to: address, amount: uint256):
    assert extcall COLLATERAL.transfer(to, amount, default_return_value=True) # dev: [cdp_erc20] transfer failed


# @dev Brings `rate_index` up to date and mints the
# interest owed since the last update to the surplus.
@internal
def _accrue():
    index: uint256 = self._rate_index()
    if index == self.rate_index:
        return
    fee: uint256 = self.total_debt_shares * (index - self.rate_index) // PRECISION
    self.rate_index = index
    self.last_accrual = block.timestamp
    if fee > 0:
        erc20._mint(self, fee)
        log Accrue(amount=fee)
        self._settle()


# @dev Burns surplus mUSD against bad debt.
@internal
def _settle():
    amount: uint256 = min(erc20.balanceOf[self], self.bad_debt)
    if amount == 0:
        return
    self.bad_debt -= amount
    erc20._burn(self, amount)
    log Settle(amount=amount)


# @dev Cuts `user`'s debt by `amount` mUSD. Repaying the
# whole debt clears every share; a partial repay rounds the
# shares removed down, in the protocol's favour.
@internal
def _repay(user: address, amount: uint256):
    d: uint256 = self._debt(user)
    assert amount <= d # dev: [cdp_erc20] repay exceeds debt
    shares: uint256 = self.debt_shares[user]
    if amount < d:
        shares = amount * PRECISION // self.rate_index
    self.debt_shares[user] -= shares
    self.total_debt_shares -= shares


# @dev The current interest index, including interest not
# yet accrued.
@view
@internal
def _rate_index() -> uint256:
    elapsed: uint256 = block.timestamp - self.last_accrual
    return self.rate_index + self.rate_index * STABILITY_FEE * elapsed // PRECISION


# @dev Shares that represent `amount` mUSD of new debt,
# rounded up in the protocol's favour.
@view
@internal
def _shares_up(amount: uint256) -> uint256:
    index: uint256 = self.rate_index
    return (amount * PRECISION + index - 1) // index


# @dev `user`'s debt in mUSD, rounded up.
@view
@internal
def _debt(user: address) -> uint256:
    return (self.debt_shares[user] * self._rate_index() + PRECISION - 1) // PRECISION


# @dev The 1e18-scaled USD value of 1e18 base units of
# the collateral token. For an 18-decimal token this is
# its USD price at 18 decimals.
@view
@internal
def _price() -> uint256:
    if SEQUENCER_UPTIME_FEED.address != empty(address):
        self._check_sequencer()

    round_id: uint80 = 0
    answer: int256 = 0
    started_at: uint256 = 0
    updated_at: uint256 = 0
    answered_in_round: uint80 = 0
    round_id, answer, started_at, updated_at, answered_in_round = staticcall ORACLE.latestRoundData()
    assert answer > 0 # dev: [cdp_erc20] invalid price
    assert block.timestamp - updated_at <= ORACLE_TIMEOUT # dev: [cdp_erc20] stale price
    return convert(answer, uint256) * PRICE_SCALE


# @dev Reverts while the L2 sequencer is down, and for
# `SEQUENCER_GRACE_PERIOD` seconds after it comes back,
# so positions aren't liquidated on prices users could
# not react to.
@view
@internal
def _check_sequencer():
    round_id: uint80 = 0
    answer: int256 = 0
    started_at: uint256 = 0
    updated_at: uint256 = 0
    answered_in_round: uint80 = 0
    round_id, answer, started_at, updated_at, answered_in_round = staticcall SEQUENCER_UPTIME_FEED.latestRoundData()
    # @dev 0 means up, 1 means down.
    assert answer == 0 # dev: [cdp_erc20] sequencer down
    # @dev Arbitrum reports 0 before the feed is initialised.
    assert started_at > 0 # dev: [cdp_erc20] sequencer down
    assert block.timestamp - started_at > SEQUENCER_GRACE_PERIOD # dev: [cdp_erc20] sequencer grace period


@view
@internal
def _collat_ratio(user: address) -> uint256:
    d: uint256 = self._debt(user)
    if d == 0:
        return max_value(uint256)
    value: uint256 = self.collateral[user] * self._price() // PRECISION
    return value * PRECISION // d
