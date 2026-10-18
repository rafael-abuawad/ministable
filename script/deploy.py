"""Deploy ministable (mUSD).

    mox run deploy                                      # pyevm, mock price feed
    mox run deploy --network anvil                      # anvil, mock price feed
    mox run deploy --network sepolia --account <name>   # Chainlink ETH/USD feed

The ETH/USD feed is the `eth_usd_price_feed` named contract in moccasin.toml.
Live networks must pin its address there; only local networks deploy a mock.
"""

from pathlib import Path
from unittest.mock import patch

import boa
from boa.contracts.abi.abi_contract import ABIContract
from boa.explorer import SESSION, Etherscan
from moccasin.boa_tools import VyperContract
from moccasin.config import Network, get_active_network

from src import ministable

IAggregatorV3 = boa.load_vyi(
    str(Path(__file__).parents[1] / "src/interfaces/IAggregatorV3.vyi")
)

NAME = "ministable"
SYMBOL = "mUSD"
DECIMALS = 18
EIP712_NAME = "ministable"
EIP712_VERSION = "1"

PRICE_FEED = "eth_usd_price_feed"
# ministable scales the answer by 1e10, so only 8-decimal feeds are supported.
PRICE_FEED_DECIMALS = 8
# Mirrors `ministable.ORACLE_TIMEOUT`; checked again after deployment.
ORACLE_TIMEOUT = 3600
ANVIL_CHAIN_ID = 31337


def _require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def _is_dev_network(network: Network) -> bool:
    return network.is_local_or_forked_network() or network.chain_id == ANVIL_CHAIN_ID


# ================= Price feed =================


def _get_price_feed(network: Network) -> ABIContract | VyperContract:
    # Without a pinned address moccasin falls back to the mock deployer
    # script, which must never happen on a live network.
    named = network.get_named_contract(PRICE_FEED)
    _require(
        _is_dev_network(network) or (named is not None and named.address is not None),
        f"No `{PRICE_FEED}` address for network '{network.name}'. "
        f"Set it under [networks.{network.name}.contracts.{PRICE_FEED}] in moccasin.toml.",
    )
    return network.manifest_named(PRICE_FEED, abi=IAggregatorV3)


def _check_price_feed(feed: ABIContract | VyperContract):
    _require(
        len(boa.env.get_code(feed.address)) > 0,
        f"No contract at price feed {feed.address}.",
    )

    decimals = feed.decimals()
    _require(
        decimals == PRICE_FEED_DECIMALS,
        f"Price feed reports {decimals} decimals, ministable requires {PRICE_FEED_DECIMALS}.",
    )

    _, answer, _, updated_at, _ = feed.latestRoundData()
    _require(answer > 0, f"Price feed returned a non-positive answer ({answer}).")
    age = boa.env.timestamp - updated_at
    _require(
        age <= ORACLE_TIMEOUT,
        f"Price feed answer is {age}s old (max {ORACLE_TIMEOUT}s); ministable would revert on every price read.",
    )
    print(
        f"Price feed {feed.address}: ${answer / 10**decimals:,.2f}, updated {age}s ago"
    )


# ================= ministable =================


def _check_deployment(stable: VyperContract, feed: ABIContract | VyperContract):
    _require(stable.ORACLE() == feed.address, "ORACLE does not match the price feed.")
    _require(
        stable.ORACLE_TIMEOUT() == ORACLE_TIMEOUT,
        "ORACLE_TIMEOUT drifted from the deploy script.",
    )
    _require(
        (stable.name(), stable.symbol(), stable.decimals()) == (NAME, SYMBOL, DECIMALS),
        "Token metadata does not match the deploy parameters.",
    )
    _, name, version, _, verifying_contract, _, _ = stable.eip712Domain()
    _require(
        (name, version, verifying_contract)
        == (EIP712_NAME, EIP712_VERSION, stable.address),
        "EIP-712 domain does not match the deploy parameters.",
    )


class _Etherscan(Etherscan):
    # titanoboa 0.2.8 sends `chainid` only in the verification POST body, but
    # Etherscan's v2 API reads it from the query string ("Missing or unsupported
    # chainid parameter"). Fixed on titanoboa master; until that ships, add the
    # query param whenever boa hasn't.
    def verify(self, *args, **kwargs):
        post = SESSION.post

        def post_with_chainid(url, **post_kwargs):
            if "chainid=" not in url:
                post_kwargs.setdefault("params", {"chainid": self.chain_id})
            return post(url, **post_kwargs)

        with patch.object(SESSION, "post", post_with_chainid):
            return super().verify(*args, **kwargs)


def _verify(network: Network, stable: VyperContract):
    if _is_dev_network(network) or not network.has_explorer():
        return
    api_key = network.explorer_api_key
    # moccasin leaves `${VAR}` unexpanded when the env var is unset.
    if network.explorer_type == "etherscan" and (
        not api_key or api_key.startswith("$")
    ):
        print("Skipping verification: no Etherscan API key configured.")
        return

    verifier_class = network.get_verifier_class()
    if verifier_class is Etherscan:
        verifier_class = _Etherscan
    verifier = verifier_class(network.explorer_uri, api_key)
    # `Network.moccasin_verify` leaves Etherscan's v2 API on chain 1.
    if hasattr(verifier, "set_chain_id"):
        verifier.set_chain_id(network.chain_id)
    try:
        boa.verify(stable, verifier).wait_for_verification()
        print("Contract verified.")
    except Exception as e:
        # The deployment itself succeeded; don't mask it with a verifier error.
        print(f"Verification failed: {e}")


def deploy() -> VyperContract:
    network = get_active_network()
    print(f"Deploying {NAME} ({SYMBOL}) to '{network.name}' from {boa.env.eoa}")

    feed = _get_price_feed(network)
    _check_price_feed(feed)

    stable: VyperContract = ministable.deploy(
        NAME, SYMBOL, DECIMALS, EIP712_NAME, EIP712_VERSION, feed.address
    )
    _check_deployment(stable, feed)
    print(f"{NAME} ({SYMBOL}) deployed at {stable.address}")

    _verify(network, stable)
    return stable


def moccasin_main() -> VyperContract:
    return deploy()
