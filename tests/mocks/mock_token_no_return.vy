# pragma version ~=0.4.3
"""
@title Mock USDT-style ERC-20
@notice `transfer` and `transferFrom` return no data,
        as on mainnet USDT. Reverts on failure.
"""


decimals: public(uint8)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])


@deploy
def __init__(decimals_: uint8):
    self.decimals = decimals_


@external
def mint(to: address, amount: uint256):
    self.balanceOf[to] += amount


@external
def approve(spender: address, amount: uint256):
    self.allowance[msg.sender][spender] = amount


@external
def transfer(to: address, amount: uint256):
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[to] += amount


@external
def transferFrom(owner: address, to: address, amount: uint256):
    self.allowance[owner][msg.sender] -= amount
    self.balanceOf[owner] -= amount
    self.balanceOf[to] += amount
