ETH = 10**18
PRECISION = 10**18
MAX_UINT256 = 2**256 - 1

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Chainlink ETH/USD feeds report 8 decimals.
ORACLE_DECIMALS = 8
ETH_USD_PRICE = 2000 * 10**ORACLE_DECIMALS

MIN_COLLAT_RATIO = 15 * 10**17
ORACLE_TIMEOUT = 3600
SEQUENCER_GRACE_PERIOD = 3600

# Largest mint against 1 ETH at $2000 that keeps the ratio >= 150%.
MAX_MINT_PER_ETH = 2000 * ETH * PRECISION // MIN_COLLAT_RATIO

# Default position opened by the `borrower_position` fixture:
# 1 ETH collateral, 1000 mUSD debt -> 200% at $2000.
POSITION_COLLATERAL = ETH
POSITION_DEBT = 1000 * ETH

# Price at which the default position sits exactly at 150%.
LIQUIDATION_PRICE = 1500 * 10**ORACLE_DECIMALS

# Stability fee: 10% a year (the contract's cap), as a per-second rate.
YEAR = 365 * 86400
MAX_STABILITY_FEE = 10**17 // YEAR
