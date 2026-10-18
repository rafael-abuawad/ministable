from tests.utils.constants import MIN_COLLAT_RATIO, PRECISION


def to_feed_price(usd: int) -> int:
    """Whole-dollar ETH/USD price in Chainlink's 8-decimal format."""
    return usd * 10**8


def max_mintable(collateral: int, feed_price: int) -> int:
    """Largest debt `collateral` wei can back at `feed_price` (mirrors `_collat_ratio`)."""
    value = collateral * feed_price * 10**10 // PRECISION
    return value * PRECISION // MIN_COLLAT_RATIO


def filter_logs(contract, event_name: str, computation=None) -> list:
    """Decoded logs of `contract`'s last call (or of `computation`) named `event_name`."""
    logs = (
        contract.get_logs(computation)
        if computation is not None
        else contract.get_logs()
    )
    return [log for log in logs if type(log).__name__ == event_name]
