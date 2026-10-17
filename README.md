# ministable (mUSD)

A minimal ETH-backed stablecoin in Vyper, inspired by DAI / Sky USD and
[MicroStable](https://github.com/shafu0x/MicroStable-World/tree/main/vyper).
Unlike MicroStable, the CDP engine lives inside the token contract: one
contract holds the ETH, tracks positions and mints/burns mUSD.

## Mechanism

- **Collateral:** native ETH. Lock it by calling `deposit()` or by sending ETH
  directly to the contract — both route through the internal `_deposit`.
- **Minimum collateral ratio:** 150%. Minting and withdrawing must leave the
  position at or above it.
- **Price:** Chainlink AggregatorV3 ETH/USD feed (8 decimals). Non-positive or
  stale (older than 1 hour) answers revert.
- **Liquidation:** any position below 150% can be fully liquidated. The
  liquidator burns the position's entire mUSD debt and receives all of its ETH.
- **Token:** ERC-20 + EIP-2612 permit, 18 decimals.

| Function | Description |
| --- | --- |
| `deposit()` / plain ETH transfer | Lock `msg.value` ETH as collateral |
| `mint(amount)` | Mint mUSD against your collateral (ratio ≥ 150%) |
| `burn(amount)` | Burn mUSD to repay your debt |
| `withdraw(amount)` | Withdraw ETH (ratio must stay ≥ 150%) |
| `liquidate(user)` | Repay all of `user`'s debt, take all of their ETH (ratio < 150%) |
| `collat_ratio(user)` | 1e18-scaled collateral ratio (`1.5e18` = 150%) |
| `collateral(user)` / `debt(user)` | Position state |

## Quickstart

```bash
mox compile        # compile
mox test           # run the test suite
mox run deploy     # deploy with a mock $2000 oracle on pyevm
```

The deploy script uses `tests/mocks/mock_aggregator.vy`. For a live network,
deploy `ministable` with the real Chainlink ETH/USD feed address instead.

## Tests

| Directory | Contents |
| --- | --- |
| `tests/unitary/ministable/` | One file per behavior: deposit, mint, burn, withdraw, liquidate, oracle, collateral ratio, ERC-20, permit |
| `tests/integration/` | Multi-step position lifecycles (open/close, rescue, liquidation with bought mUSD) |
| `tests/fuzz/` | Hypothesis: exact mint/withdraw bounds, and a stateful model checking solvency invariants |
| `tests/mocks/` | Mock Chainlink feed and a contract position holder (ETH rejection, reentrancy) |

```bash
mox test tests/unitary   # fast unit tests only
mox test tests/fuzz      # property + stateful fuzzing (~45s)
```
