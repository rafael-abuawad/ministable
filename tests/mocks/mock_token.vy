# pragma version ~=0.4.3
"""
@title Mock ERC-20 collateral token
@notice Configurable to behave like the awkward tokens
        `cdp_erc20` must handle: any decimals, a fee
        taken on every transfer, `transfer`/`transferFrom`
        returning `False` instead of reverting, and a hook
        that calls an arbitrary contract on each transfer
        (to exercise re-entrancy).
"""


name: public(String[25])
symbol: public(String[5])
decimals: public(uint8)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)

# Share of every transfer burned, in basis points.
fee_bps: public(uint256)
# When set, `transfer`/`transferFrom` move nothing and return `False`.
return_false: public(bool)
# When set, every transfer ends with `raw_call(hook_target, hook_data)`.
hook_target: public(address)
hook_data: public(Bytes[256])


event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256


event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256


@deploy
def __init__(decimals_: uint8):
    self.name = "Mock Token"
    self.symbol = "MOCK"
    self.decimals = decimals_


@external
def mint(to: address, amount: uint256):
    self.balanceOf[to] += amount
    self.totalSupply += amount
    log Transfer(sender=empty(address), receiver=to, value=amount)


@external
def set_fee_bps(fee_bps: uint256):
    assert fee_bps <= 10_000
    self.fee_bps = fee_bps


@external
def set_return_false(return_false: bool):
    self.return_false = return_false


@external
def set_hook(target: address, data: Bytes[256]):
    self.hook_target = target
    self.hook_data = data


@external
def approve(spender: address, amount: uint256) -> bool:
    self.allowance[msg.sender][spender] = amount
    log Approval(owner=msg.sender, spender=spender, value=amount)
    return True


@external
def transfer(to: address, amount: uint256) -> bool:
    if self.return_false:
        return False
    self._transfer(msg.sender, to, amount)
    return True


@external
def transferFrom(owner: address, to: address, amount: uint256) -> bool:
    if self.return_false:
        return False
    if self.allowance[owner][msg.sender] != max_value(uint256):
        self.allowance[owner][msg.sender] -= amount
    self._transfer(owner, to, amount)
    return True


@internal
def _transfer(owner: address, to: address, amount: uint256):
    fee: uint256 = amount * self.fee_bps // 10_000
    self.balanceOf[owner] -= amount
    self.balanceOf[to] += amount - fee
    self.totalSupply -= fee
    log Transfer(sender=owner, receiver=to, value=amount - fee)
    if self.hook_target != empty(address):
        raw_call(self.hook_target, self.hook_data)
