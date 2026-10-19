from moccasin.boa_tools import VyperContract
from moccasin.config import get_active_network

from tests.mocks import mock_aggregator
from tests.utils.constants import ETH_USD_PRICE, ORACLE_DECIMALS

ANVIL_CHAIN_ID = 31337
# No Chainlink MON/USD feed exists here. The mock's setters are owner-gated.
MONAD_TESTNET_CHAIN_ID = 10143


def deploy_price_feed() -> VyperContract:
    network = get_active_network()
    # Last line of defence: a mock oracle on a live network would let
    # anyone with the mock's setters drain every position. Monad testnet
    # is the one exception, and only because its mock is owner-gated.
    allowed = network.is_local_or_forked_network() or network.chain_id in {
        ANVIL_CHAIN_ID,
        MONAD_TESTNET_CHAIN_ID,
    }
    if not allowed:
        raise RuntimeError(
            f"Refusing to deploy a mock price feed on live network '{network.name}'."
        )
    feed: VyperContract = mock_aggregator.deploy(ETH_USD_PRICE, ORACLE_DECIMALS)
    price = ETH_USD_PRICE / 10**ORACLE_DECIMALS
    print(
        f"Mock native coin / USD price feed deployed at {feed.address} "
        f"(${price:,.2f}, only {feed.owner()} can update it)."
    )
    return feed


def moccasin_main() -> VyperContract:
    return deploy_price_feed()
