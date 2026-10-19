# pragma version ~=0.4.3
"""
@title Mock Chainlink AggregatorV3
@notice Doubles as an L2 sequencer uptime feed: an
        answer of 0 means up, 1 means down, and
        `started_at` is when that status began.
"""


from interfaces import IAggregatorV3
implements: IAggregatorV3


answer: public(int256)
started_at: public(uint256)
updated_at: public(uint256)
_decimals: uint8
# The deployer. Setters are not public: this mock is what Monad testnet
# deploys in place of a Chainlink MON/USD feed.
owner: public(immutable(address))


@deploy
def __init__(answer: int256, decimals_: uint8):
    owner = msg.sender
    self.answer = answer
    self.started_at = block.timestamp
    self.updated_at = block.timestamp
    self._decimals = decimals_


@internal
def _check_owner():
    assert msg.sender == owner  # dev: [mock_aggregator] not owner


@external
def set_answer(answer: int256):
    self._check_owner()
    self.answer = answer
    self.started_at = block.timestamp
    self.updated_at = block.timestamp


@external
def set_started_at(started_at: uint256):
    self._check_owner()
    self.started_at = started_at


@external
def set_updated_at(updated_at: uint256):
    self._check_owner()
    self.updated_at = updated_at


@view
@external
def decimals() -> uint8:
    return self._decimals


@view
@external
def latestRoundData() -> (uint80, int256, uint256, uint256, uint80):
    return (1, self.answer, self.started_at, self.updated_at, 1)
