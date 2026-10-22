# pragma version ~=0.4.3
"""
@title Test harness for the `erc20` module
@notice Exposes the module's internal `_mint` and `_burn`
        so the token can be tested without a CDP engine
        minting it.
"""


from snekmate.auth import ownable as ow
initializes: ow


from modules import erc20
initializes: erc20[ownable := ow]


exports: erc20.__interface__


@deploy
def __init__(
    name_: String[25],
    symbol_: String[5],
    decimals_: uint8,
    name_eip712_: String[50],
    version_eip712_: String[20],
):
    ow.__init__()
    erc20.__init__(name_, symbol_, decimals_, name_eip712_, version_eip712_)


@external
def mint(owner: address, amount: uint256):
    erc20._mint(owner, amount)


@external
def burn(owner: address, amount: uint256):
    erc20._burn(owner, amount)
