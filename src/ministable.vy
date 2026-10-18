# pragma version ~=0.4.3
# pragma nonreentrancy on
"""
@title ministable: ETH-backed stablecoin (mUSD)
@custom:contract-name ministable
@notice The CDP engine lives in the token itself. Users lock
        ETH (via `deposit` or a plain ETH transfer) and mint
        mUSD against it at a minimum 150% collateral ratio.
        Positions below 150% can be fully liquidated: the
        liquidator burns the whole debt and receives all of
        the position's ETH.
@license GNU Affero General Public License v3.0 only
@author rafael-abuawad
"""


# @dev We import and implement the `IERC20` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC20
implements: IERC20


# @dev We import and implement the `IERC20Detailed` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC20Detailed
implements: IERC20Detailed


# @dev We import and implement the `IERC20Permit`
# interfacex.
from snekmate.tokens.interfaces import IERC20Permit
implements: IERC20Permit


# @dev We import and implement the `IERC5267` interface,
from snekmate.utils.interfaces import IERC5267
implements: IERC5267


# @dev We import the `IAggregatorV3` interface
# for the Chainlink ETH/USD price feed.
from .interfaces import IAggregatorV3


# @dev We import and initialise the `ownable` module.
from snekmate.auth import ownable as ow
initializes: ow


# @dev We import and initialise the `erc20` module.
from modules import erc20
initializes: erc20[ownable := ow]


# @dev We export all `external` functions
# from the `erc20` module.
exports: erc20.__interface__


# @dev Minimum collateral ratio, 1e18-scaled (150%).
MIN_COLLAT_RATIO: public(constant(uint256)) = 15 * 10**17


# @dev Time the L2 sequencer must have been back up
# before prices are trusted again, in seconds.
SEQUENCER_GRACE_PERIOD: public(constant(uint256)) = 3600


# @dev Largest allowed stability fee: 10% a year, as a
# 1e18-scaled per-second rate.
MAX_STABILITY_FEE: public(constant(uint256)) = 10**17 // (365 * 86400)


# @dev Constant to calculate the precision.
PRECISION: constant(uint256) = 10**18


# @dev The ETH/USD price feed.
ORACLE: public(immutable(IAggregatorV3))


# @dev Maximum age of an oracle answer, in seconds.
# Set per network at deployment: the feed's heartbeat
# plus a buffer.
ORACLE_TIMEOUT: public(immutable(uint256))


# @dev Scales an oracle answer to 18 decimals.
PRICE_SCALE: immutable(uint256)


# @dev The Chainlink L2 sequencer uptime feed, or
# `empty(address)` on networks without a sequencer.
SEQUENCER_UPTIME_FEED: public(immutable(IAggregatorV3))


# @dev Interest charged on debt, as a 1e18-scaled
# per-second rate. Fixed at deployment.
STABILITY_FEE: public(immutable(uint256))


# @dev Returns the ETH (in wei) locked by an `address`.
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


# @dev Returns the ETH (in wei) paid for surplus mUSD.
reserve: public(uint256)


# @dev Emitted when `user` locks `amount` wei
# of ETH as collateral, either via `deposit` or
# a plain ETH transfer.
event Deposit:
    user: indexed(address)
    amount: uint256


# @dev Emitted when `user` withdraws `amount`
# wei of ETH collateral.
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


# @dev Emitted when `buyer` pays `eth` wei for
# `amount` mUSD from the surplus.
event BuySurplus:
    buyer: indexed(address)
    eth: uint256
    amount: uint256


# @dev Emitted when `liquidator` burns all of
# `user`'s `debt` (mUSD) and receives all of
# their `collateral` (wei).
event Liquidate:
    liquidator: indexed(address)
    user: indexed(address)
    debt: uint256
    collateral: uint256


@deploy
@payable
def __init__(
    name_: String[25],
    symbol_: String[5],
    decimals_: uint8,
    name_eip712_: String[50],
    version_eip712_: String[20],
    oracle: IAggregatorV3,
    oracle_timeout_: uint256,
    sequencer_uptime_feed_: IAggregatorV3,
    stability_fee_: uint256,
):
    ow.__init__()
    erc20.__init__(name_, symbol_, decimals_, name_eip712_, version_eip712_)
    assert oracle_timeout_ > 0 # dev: [ministable] zero oracle timeout
    oracle_decimals: uint8 = staticcall oracle.decimals()
    assert oracle_decimals <= 18 # dev: [ministable] unsupported oracle decimals
    ORACLE = oracle
    ORACLE_TIMEOUT = oracle_timeout_
    PRICE_SCALE = 10 ** (18 - convert(oracle_decimals, uint256))
    SEQUENCER_UPTIME_FEED = sequencer_uptime_feed_
    assert stability_fee_ <= MAX_STABILITY_FEE # dev: [ministable] stability fee too high
    STABILITY_FEE = stability_fee_
    self.rate_index = PRECISION
    self.last_accrual = block.timestamp


# @dev Plain ETH transfers are treated as deposits.
@payable
@external
def __default__():
    self._deposit(msg.sender, msg.value)


# @dev Locks the sent ETH as collateral for `msg.sender`.
@payable
@external
def deposit():
    self._deposit(msg.sender, msg.value)


# @dev Mints `amount` mUSD against the caller's collateral.
@external
def mint(amount: uint256):
    self._accrue()
    shares: uint256 = self._shares_up(amount)
    self.debt_shares[msg.sender] += shares
    self.total_debt_shares += shares
    assert self._collat_ratio(msg.sender) >= MIN_COLLAT_RATIO # dev: [ministable] undercollateralized
    erc20._mint(msg.sender, amount)
    log Mint(user=msg.sender, amount=amount)


# @dev Burns `amount` mUSD to repay the caller's debt.
@external
def burn(amount: uint256):
    self._accrue()
    self._repay(msg.sender, amount)
    erc20._burn(msg.sender, amount)
    log Burn(user=msg.sender, amount=amount)


# @dev Withdraws `amount` wei of the caller's collateral.
@external
def withdraw(amount: uint256):
    self._accrue()
    self.collateral[msg.sender] -= amount
    assert self._collat_ratio(msg.sender) >= MIN_COLLAT_RATIO # dev: [ministable] undercollateralized
    log Withdraw(user=msg.sender, amount=amount)
    raw_call(msg.sender, b"", value=amount)


# @dev Liquidates an undercollateralized `user`: the caller
# burns the user's whole debt and receives all of their ETH.
@external
def liquidate(user: address):
    self._accrue()
    assert self._collat_ratio(user) < MIN_COLLAT_RATIO # dev: [ministable] position healthy
    d: uint256 = self._debt(user)
    c: uint256 = self.collateral[user]
    self.total_debt_shares -= self.debt_shares[user]
    self.debt_shares[user] = 0
    self.collateral[user] = 0
    erc20._burn(msg.sender, d)
    log Liquidate(liquidator=msg.sender, user=user, debt=d, collateral=c)
    raw_call(msg.sender, b"", value=c)


# @dev Sells surplus mUSD for the sent ETH at the oracle
# price. Interest is minted to the surplus, so this is how
# it reaches borrowers who need it to repay. The ETH is
# kept in the reserve.
@payable
@external
def buy_surplus() -> uint256:
    self._accrue()
    amount: uint256 = msg.value * self._price() // PRECISION
    assert amount > 0 # dev: [ministable] zero purchase
    assert amount <= erc20.balanceOf[self] # dev: [ministable] not enough surplus
    self.reserve += msg.value
    erc20._transfer(self, msg.sender, amount)
    log BuySurplus(buyer=msg.sender, eth=msg.value, amount=amount)
    return amount


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


@internal
def _deposit(user: address, amount: uint256):
    assert amount > 0 # dev: [ministable] zero deposit
    self.collateral[user] += amount
    log Deposit(user=user, amount=amount)


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


# @dev Cuts `user`'s debt by `amount` mUSD. Repaying the
# whole debt clears every share; a partial repay rounds the
# shares removed down, in the protocol's favour.
@internal
def _repay(user: address, amount: uint256):
    d: uint256 = self._debt(user)
    assert amount <= d # dev: [ministable] repay exceeds debt
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
    assert answer > 0 # dev: [ministable] invalid price
    assert block.timestamp - updated_at <= ORACLE_TIMEOUT # dev: [ministable] stale price
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
    assert answer == 0 # dev: [ministable] sequencer down
    # @dev Arbitrum reports 0 before the feed is initialised.
    assert started_at > 0 # dev: [ministable] sequencer down
    assert block.timestamp - started_at > SEQUENCER_GRACE_PERIOD # dev: [ministable] sequencer grace period


@view
@internal
def _collat_ratio(user: address) -> uint256:
    d: uint256 = self._debt(user)
    if d == 0:
        return max_value(uint256)
    value: uint256 = self.collateral[user] * self._price() // PRECISION
    return value * PRECISION // d
