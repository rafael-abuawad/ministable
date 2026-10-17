# pragma version ~=0.4.3
"""
@title Mock Chainlink AggregatorV3 (8 decimals)
"""


from interfaces import IAggregatorV3
implements: IAggregatorV3


answer: public(int256)
updated_at: public(uint256)


@deploy
def __init__(answer: int256):
    self.answer = answer
    self.updated_at = block.timestamp


@external
def set_answer(answer: int256):
    self.answer = answer
    self.updated_at = block.timestamp


@external
def set_updated_at(updated_at: uint256):
    self.updated_at = updated_at


@view
@external
def decimals() -> uint8:
    return 8


@view
@external
def latestRoundData() -> (uint80, int256, uint256, uint256, uint80):
    return (1, self.answer, self.updated_at, self.updated_at, 1)
