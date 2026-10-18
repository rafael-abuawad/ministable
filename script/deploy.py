"""Deploy ministable (mUSD).

    mox run deploy                                      # pyevm, mock price feed
    mox run deploy --network anvil                      # anvil, mock price feed
    mox run deploy --network sepolia --account <name>   # Chainlink price feed

Collateral is the chain's native coin (ETH, MON on Monad, S on Sonic), priced
by the `native_usd_price_feed` named contract in moccasin.toml, which must
quote that coin in USD.
Live networks must pin its address there; only local networks deploy a mock.
Live networks also set `oracle_timeout` (the feed's heartbeat plus a buffer)
under `extra_data`, and L2s pin a `sequencer_uptime_feed`.
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

PRICE_FEED = "native_usd_price_feed"
SEQUENCER_FEED = "sequencer_uptime_feed"
# ministable scales answers up to 18 decimals, so feeds can't report more.
MAX_PRICE_FEED_DECIMALS = 18
# Used on local networks only; live networks must set `oracle_timeout`.
DEV_ORACLE_TIMEOUT = 3600
# Mirrors `ministable.SEQUENCER_GRACE_PERIOD`.
SEQUENCER_GRACE_PERIOD = 3600
# 2% a year, as the 1e18-scaled per-second rate ministable expects.
STABILITY_FEE = 2 * 10**16 // (365 * 86400)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ANVIL_CHAIN_ID = 31337
# Rollups whose sequencer can go down; deploying there needs an uptime feed.
L2_CHAIN_IDS = {42161}


def _require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


def _is_dev_network(network: Network) -> bool:
    return network.is_local_or_forked_network() or network.chain_id == ANVIL_CHAIN_ID


# ================= Price feed =================


def _is_live_l2(network: Network) -> bool:
    return network.chain_id in L2_CHAIN_IDS


def _oracle_timeout(network: Network) -> int:
    timeout = network.extra_data.get("oracle_timeout")
    if timeout is None and _is_dev_network(network):
        return DEV_ORACLE_TIMEOUT
    _require(
        isinstance(timeout, int) and timeout > 0,
        f"No `oracle_timeout` for network '{network.name}'. Set it under "
        f"[networks.{network.name}.extra_data] to the feed's heartbeat plus a buffer.",
    )
    return timeout


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


def _check_price_feed(feed: ABIContract | VyperContract, timeout: int):
    _require(
        len(boa.env.get_code(feed.address)) > 0,
        f"No contract at price feed {feed.address}.",
    )

    decimals = feed.decimals()
    _require(
        decimals <= MAX_PRICE_FEED_DECIMALS,
        f"Price feed reports {decimals} decimals, ministable supports at most {MAX_PRICE_FEED_DECIMALS}.",
    )

    _, answer, _, updated_at, _ = feed.latestRoundData()
    _require(answer > 0, f"Price feed returned a non-positive answer ({answer}).")
    age = boa.env.timestamp - updated_at
    _require(
        age <= timeout,
        f"Price feed answer is {age}s old (max {timeout}s); ministable would revert on every price read.",
    )
    print(
        f"Price feed {feed.address}: ${answer / 10**decimals:,.2f}, updated {age}s ago"
    )


def _get_sequencer_feed(network: Network) -> ABIContract | None:
    named = network.get_named_contract(SEQUENCER_FEED)
    address = named.address if named is not None else None
    _require(
        address is not None or not _is_live_l2(network),
        f"No `{SEQUENCER_FEED}` address for L2 network '{network.name}'. "
        f"Set it under [networks.{network.name}.contracts.{SEQUENCER_FEED}] in moccasin.toml.",
    )
    if address is None:
        return None
    return IAggregatorV3.at(address)


def _check_sequencer_feed(feed: ABIContract):
    _require(
        len(boa.env.get_code(feed.address)) > 0,
        f"No contract at sequencer uptime feed {feed.address}.",
    )
    _, answer, started_at, _, _ = feed.latestRoundData()
    _require(answer == 0, "Sequencer uptime feed reports the sequencer is down.")
    up_for = boa.env.timestamp - started_at
    _require(
        started_at > 0 and up_for > SEQUENCER_GRACE_PERIOD,
        f"Sequencer has been up for {up_for}s, inside the {SEQUENCER_GRACE_PERIOD}s grace period.",
    )
    print(f"Sequencer uptime feed {feed.address}: up for {up_for}s")


# ================= ministable =================


def _constructor_args(
    feed: ABIContract | VyperContract,
    timeout: int,
    sequencer: ABIContract | None,
) -> tuple:
    return (
        NAME,
        SYMBOL,
        DECIMALS,
        EIP712_NAME,
        EIP712_VERSION,
        feed.address,
        timeout,
        sequencer.address if sequencer is not None else ZERO_ADDRESS,
        STABILITY_FEE,
    )


def _check_deployment(
    stable: VyperContract,
    feed: ABIContract | VyperContract,
    timeout: int,
    sequencer: ABIContract | None,
):
    _require(stable.ORACLE() == feed.address, "ORACLE does not match the price feed.")
    _require(
        stable.ORACLE_TIMEOUT() == timeout,
        "ORACLE_TIMEOUT does not match the network's `oracle_timeout`.",
    )
    _require(
        stable.SEQUENCER_UPTIME_FEED()
        == (sequencer.address if sequencer is not None else ZERO_ADDRESS),
        "SEQUENCER_UPTIME_FEED does not match the network's sequencer feed.",
    )
    _require(
        stable.STABILITY_FEE() == STABILITY_FEE,
        "STABILITY_FEE does not match the deploy script.",
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
    timeout = _oracle_timeout(network)
    _check_price_feed(feed, timeout)
    sequencer = _get_sequencer_feed(network)
    if sequencer is not None:
        _check_sequencer_feed(sequencer)

    stable: VyperContract = ministable.deploy(
        *_constructor_args(feed, timeout, sequencer)
    )
    _check_deployment(stable, feed, timeout, sequencer)
    print(f"{NAME} ({SYMBOL}) deployed at {stable.address}")

    _verify(network, stable)
    return stable


def moccasin_main() -> VyperContract:
    return deploy()
