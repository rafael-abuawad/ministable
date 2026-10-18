"""Verify an already-deployed ministable (mUSD) on the block explorer.

    mox run verify --network arbitrum

Targets the latest ministable deployment moccasin recorded for the network
(in .deployments.db), e.g. when `mox run deploy` succeeded but verification
failed. Sends no transactions.
"""

from moccasin.boa_tools import VyperContract
from moccasin.config import get_active_network

from script.deploy import (
    _check_deployment,
    _constructor_args,
    _get_price_feed,
    _require,
    _verify,
)
from src import ministable


def verify() -> VyperContract:
    network = get_active_network()
    deployed = network.get_latest_contract_unchecked("ministable")
    _require(
        deployed is not None,
        f"No ministable deployment recorded for network '{network.name}'.",
    )

    stable: VyperContract = ministable.at(deployed.address)
    feed = _get_price_feed(network)
    # `at()` doesn't know the constructor arguments, which the explorer needs
    # to match the creation bytecode. `_check_deployment` confirms they agree
    # with the on-chain state.
    stable.ctor_calldata = stable._ctor.prepare_calldata(*_constructor_args(feed))
    _check_deployment(stable, feed)
    print(f"Verifying ministable at {stable.address} on '{network.name}'")

    _verify(network, stable)
    return stable


def moccasin_main() -> VyperContract:
    return verify()
