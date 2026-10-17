# pragma version ~=0.4.3
# pragma nonreentrancy off
"""
@title Modern and Gas-Efficient ERC-20 + EIP-2612 Implementation
@custom:contract-name erc20
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


# @dev We import and initialise the `ownable` module.
from snekmate.auth import ownable as ow
initializes: ow


# @dev We import and initialise the `erc20` module.
from modules import erc20
initializes: erc20[ownable := ow]


# @dev We export all `external` functions
# from the `erc20` module.
exports: erc20.__interface__


@deploy
@payable
def __init__():
    ow.__init__()
    erc20.__init__("ministable", "1")


# @dev Returns the name of the token.
@view
@external
def name() -> String[10]:
    return "ministable"


# @dev Returns the symbol of the token.
@view
@external
def symbol() -> String[4]:
    return "mUSD"


# @dev Returns the decimal places of the token.
@view
@external
def decimals() -> uint8:
    return 6
