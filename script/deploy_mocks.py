from moccasin.boa_tools import VyperContract
from moccasin.config import get_active_network

from tests.mocks import mock_aggregator
from tests.utils.constants import ETH_USD_PRICE, ORACLE_DECIMALS

ANVIL_CHAIN_ID = 31337


def deploy_price_feed() -> VyperContract:
    network = get_active_network()
    # Last line of defence: a mock oracle on a live network would let
    # anyone with the mock's setters drain every position.
    if not (network.is_local_or_forked_network() or network.chain_id == ANVIL_CHAIN_ID):
        raise RuntimeError(
            f"Refusing to deploy a mock price feed on live network '{network.name}'."
        )
    feed: VyperContract = mock_aggregator.deploy(ETH_USD_PRICE, ORACLE_DECIMALS)
    print(f"Mock ETH/USD price feed deployed at {feed.address}")
    return feed


def moccasin_main() -> VyperContract:
    return deploy_price_feed()
