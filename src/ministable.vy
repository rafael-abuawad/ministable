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


# @dev Maximum age of an oracle answer, in seconds.
ORACLE_TIMEOUT: public(constant(uint256)) = 3600


# @dev Constant to calculate the precision.
PRECISION: constant(uint256) = 10**18


# @dev The ETH/USD price feed.
ORACLE: public(immutable(IAggregatorV3))


# @dev Returns the ETH (in wei) locked by an `address`.
collateral: public(HashMap[address, uint256])


# @dev Returns the mUSD minted by an `address`.
debt: public(HashMap[address, uint256])


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
    oracle: IAggregatorV3,
):
    ow.__init__()
    erc20.__init__(name_, symbol_, decimals_, name_, "1")
    ORACLE = oracle


# @dev Locks the sent ETH as collateral for `msg.sender`.
@payable
@external
def deposit():
    self._deposit(msg.sender, msg.value)


# @dev Plain ETH transfers are treated as deposits.
@payable
@external
def __default__():
    self._deposit(msg.sender, msg.value)


# @dev Mints `amount` mUSD against the caller's collateral.
@external
def mint(amount: uint256):
    self.debt[msg.sender] += amount
    assert self._collat_ratio(msg.sender) >= MIN_COLLAT_RATIO, "ministable: undercollateralized"
    erc20._mint(msg.sender, amount)
    log Mint(user=msg.sender, amount=amount)


# @dev Burns `amount` mUSD to repay the caller's debt.
@external
def burn(amount: uint256):
    self.debt[msg.sender] -= amount
    erc20._burn(msg.sender, amount)
    log Burn(user=msg.sender, amount=amount)


# @dev Withdraws `amount` wei of the caller's collateral.
@external
def withdraw(amount: uint256):
    self.collateral[msg.sender] -= amount
    assert self._collat_ratio(msg.sender) >= MIN_COLLAT_RATIO, "ministable: undercollateralized"
    log Withdraw(user=msg.sender, amount=amount)
    raw_call(msg.sender, b"", value=amount)


# @dev Liquidates an undercollateralized `user`: the caller
# burns the user's whole debt and receives all of their ETH.
@external
def liquidate(user: address):
    assert self._collat_ratio(user) < MIN_COLLAT_RATIO, "ministable: position healthy"
    d: uint256 = self.debt[user]
    c: uint256 = self.collateral[user]
    self.debt[user] = 0
    self.collateral[user] = 0
    erc20._burn(msg.sender, d)
    log Liquidate(liquidator=msg.sender, user=user, debt=d, collateral=c)
    raw_call(msg.sender, b"", value=c)


# @dev Returns the 1e18-scaled collateral ratio of `user`.
@view
@external
def collat_ratio(user: address) -> uint256:
    return self._collat_ratio(user)


@internal
def _deposit(user: address, amount: uint256):
    assert amount > 0, "ministable: zero deposit"
    self.collateral[user] += amount
    log Deposit(user=user, amount=amount)


@view
@internal
def _price() -> uint256:
    round_id: uint80 = 0
    answer: int256 = 0
    started_at: uint256 = 0
    updated_at: uint256 = 0
    answered_in_round: uint80 = 0
    round_id, answer, started_at, updated_at, answered_in_round = staticcall ORACLE.latestRoundData()
    assert answer > 0, "ministable: invalid price"
    assert block.timestamp - updated_at <= ORACLE_TIMEOUT, "ministable: stale price"
    # @dev 8-decimal feed scaled to 18 decimals.
    return convert(answer, uint256) * 10**10


@view
@internal
def _collat_ratio(user: address) -> uint256:
    d: uint256 = self.debt[user]
    if d == 0:
        return max_value(uint256)
    value: uint256 = self.collateral[user] * self._price() // PRECISION
    return value * PRECISION // d
