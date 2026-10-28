# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Stablecoin factory
@custom:contract-name factory
@notice Deploys `ministable` contracts from an ERC-5202 blueprint.
        One owner controls every deployment. Ownership moves in two
        steps: the owner nominates a successor, and that account
        must accept before it takes effect.
@license GNU Affero General Public License v3.0 only
@author rafael-abuawad
"""


# @dev The implementation deployed by `deploy_ministable`.
# Importing it exposes `ministable.__interface__` and the
# constructor argument types.
from . import ministable


# @dev Chainlink feed type, matching `ministable`'s constructor.
from modules.cdp.interfaces import IAggregatorV3


# @dev We import and initialise the `ownable` module.
# `ownable_2step` uses it, so this contract owns that state.
from snekmate.auth import ownable as ow
initializes: ow


# @dev We import and initialise the `ownable_2step` module.
from snekmate.auth import ownable_2step as ow2step
initializes: ow2step[ownable := ow]


# @dev `owner` is re-exported by `ownable_2step`. The two-step
# transfer, accept, and renounce functions replace `ownable`'s
# single-step versions, so those are not exported.
exports: ow2step.__interface__


# @dev ERC-5202 preamble (`0xfe7100`) that `create_from_blueprint`
# skips with the default `code_offset` of 3. A blueprint without
# it can be called as a normal contract, which would run the
# `ministable` constructor.
_ERC5202_PREAMBLE: constant(bytes3) = 0xFE7100


# @dev Most deployments one factory will record.
MAX_MINISTABLES: public(constant(uint256)) = 64


# @dev Blueprint whose initcode `deploy_ministable` runs.
MINISTABLE_BLUEPRINT: public(immutable(ministable.__interface__))


# @dev Ministables this factory has deployed, in order.
ministables: public(DynArray[address, MAX_MINISTABLES])


# @dev `True` when `stable` was deployed by this factory.
is_ministable: public(HashMap[address, bool])


# @dev Emitted when `owner` deploys `stable`.
event MinistableDeployed:
    stable: indexed(address)
    owner: indexed(address)


@deploy
@payable
def __init__(ministable_: ministable.__interface__):
    """
    @dev `payable` so creation does not check `msg.value`.
         The deployer of this contract becomes its owner.
    @param ministable_ An ERC-5202 blueprint of `ministable`.
    """
    ow.__init__()
    ow2step.__init__()
    assert ministable_.address.codesize >= 3  # dev: [factory] blueprint is not a contract
    assert convert(slice(ministable_.address.code, 0, 3), bytes3) == _ERC5202_PREAMBLE  # dev: [factory] not an erc-5202 blueprint
    MINISTABLE_BLUEPRINT = ministable_


@external
def deploy_ministable(
    name_: String[25],
    symbol_: String[5],
    decimals_: uint8,
    name_eip712_: String[50],
    version_eip712_: String[20],
    oracle: IAggregatorV3,
    oracle_timeout_: uint256,
    sequencer_uptime_feed_: IAggregatorV3,
    stability_fee_: uint256,
) -> address:
    """
    @dev Deploys a `ministable` from `MINISTABLE_BLUEPRINT`.
         Only the factory owner may call this. The new
         contract's owner is this factory, because
         `ministable` assigns ownership to `msg.sender`
         and the blueprint constructor runs in that context.
    @param name_ The ERC-20 name. At most 25 characters.
    @param symbol_ The ERC-20 symbol. At most 5 characters.
    @param decimals_ The ERC-20 decimals.
    @param name_eip712_ The EIP-712 domain name. At most 50 characters.
    @param version_eip712_ The EIP-712 domain version. At most 20 characters.
    @param oracle The native coin / USD price feed.
    @param oracle_timeout_ Maximum age of an oracle answer, in seconds.
    @param sequencer_uptime_feed_ The L2 sequencer feed, or the zero address.
    @param stability_fee_ The per-second stability fee, 1e18-scaled.
    @return address The deployed `ministable`.
    """
    ow._check_owner()
    assert len(self.ministables) < MAX_MINISTABLES  # dev: [factory] deployment limit reached

    stable: address = create_from_blueprint(
        MINISTABLE_BLUEPRINT.address,
        name_,
        symbol_,
        decimals_,
        name_eip712_,
        version_eip712_,
        oracle,
        oracle_timeout_,
        sequencer_uptime_feed_,
        stability_fee_,
        code_offset=3,
    )
    self.ministables.append(stable)
    self.is_ministable[stable] = True
    log MinistableDeployed(stable=stable, owner=msg.sender)
    return stable


@external
@view
def n_ministables() -> uint256:
    """
    @dev Returns how many ministables this factory has deployed.
    @return uint256 The number of entries in `ministables`.
    """
    return len(self.ministables)
