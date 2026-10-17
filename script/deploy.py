from src import ministable
from tests.mocks import mock_aggregator
from moccasin.boa_tools import VyperContract

ETH_USD_PRICE = 2000 * 10**8


def deploy() -> VyperContract:
    oracle: VyperContract = mock_aggregator.deploy(ETH_USD_PRICE)
    stable: VyperContract = ministable.deploy(oracle.address)
    print(f"ministable (mUSD) deployed at {stable.address}, oracle at {oracle.address}")
    return stable


def moccasin_main() -> VyperContract:
    return deploy()
