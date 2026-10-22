# pragma version ~=0.4.3
"""
@title Mock cdp_native position holder
@notice A contract that opens a cdp_native position. Its
        `__default__` can be toggled to reject ETH or to
        re-enter `withdraw` when it receives ETH.
"""


interface IMinistable:
    def deposit(): payable
    def mint(amount: uint256): nonpayable
    def withdraw(amount: uint256): nonpayable


STABLE: public(immutable(IMinistable))


accept_eth: public(bool)
reenter: public(bool)


@deploy
def __init__(stable: IMinistable):
    STABLE = stable
    self.accept_eth = True


@external
def set_accept_eth(accept_eth: bool):
    self.accept_eth = accept_eth


@external
def set_reenter(reenter: bool):
    self.reenter = reenter


@payable
@external
def deposit():
    extcall STABLE.deposit(value=msg.value)


@external
def mint(amount: uint256):
    extcall STABLE.mint(amount)


@external
def withdraw(amount: uint256):
    extcall STABLE.withdraw(amount)


@payable
@external
def __default__():
    assert self.accept_eth, "receiver: eth rejected"
    if self.reenter:
        extcall STABLE.withdraw(msg.value)
