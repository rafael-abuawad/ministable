from src import ministable
from tests.utils.constants import (
    LIQUIDATION_PENALTY,
    MIN_COLLAT_RATIO,
    ORACLE_DECIMALS,
    ORACLE_TIMEOUT,
    PRECISION,
    ZERO_ADDRESS,
)


def deploy_stable(oracle, timeout=ORACLE_TIMEOUT, sequencer=ZERO_ADDRESS, fee=0):
    """ministable with the test suite's token metadata. Interest-free by default,
    so debts stay equal to the mUSD minted."""
    return ministable.deploy(
        "ministable", "mUSD", 18, "ministable", "1", oracle, timeout, sequencer, fee
    )


def to_feed_price(usd: int, decimals: int = ORACLE_DECIMALS) -> int:
    """Whole-dollar ETH/USD price in a Chainlink feed's format."""
    return usd * 10**decimals


def max_mintable(collateral: int, feed_price: int, decimals: int = ORACLE_DECIMALS) -> int:
    """Largest debt `collateral` wei can back at `feed_price` (mirrors `_collat_ratio`)."""
    value = collateral * feed_price * 10 ** (18 - decimals) // PRECISION
    return value * PRECISION // MIN_COLLAT_RATIO


def filter_logs(contract, event_name: str, computation=None) -> list:
    """Decoded logs of `contract`'s last call (or of `computation`) named `event_name`."""
    logs = (
        contract.get_logs(computation)
        if computation is not None
        else contract.get_logs()
    )
    return [log for log in logs if type(log).__name__ == event_name]


def liquidation(
    collateral: int, debt: int, feed_price: int, max_repay: int, decimals: int = ORACLE_DECIMALS
) -> tuple[int, int, int]:
    """(repaid, seized, written_off) for a liquidation (mirrors `liquidate`)."""
    price = feed_price * 10 ** (18 - decimals)
    value = collateral * price // PRECISION * PRECISION
    if value >= LIQUIDATION_PENALTY * debt:
        step = MIN_COLLAT_RATIO - LIQUIDATION_PENALTY
        needed = MIN_COLLAT_RATIO * debt - value
        repay = min(-(-needed // step), debt, max_repay)
        return repay, min(repay * LIQUIDATION_PENALTY // price, collateral), 0
    repay = value // LIQUIDATION_PENALTY
    return repay, collateral, debt - repay
