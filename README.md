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
- **Price:** Chainlink AggregatorV3 ETH/USD feed (any decimals up to 18).
  Non-positive or stale answers revert. The staleness limit, `ORACLE_TIMEOUT`,
  is set per network at deployment (the feed's heartbeat plus a buffer) and is
  immutable afterwards.
- **L2 sequencer:** on L2s, the contract reads Chainlink's sequencer uptime
  feed and refuses to price positions while the sequencer is down and for an
  hour after it returns. `deposit`, `burn` and debt-free `withdraw` never read
  the price, so users can always repay and exit.
- **Stability fee:** debt grows at a fixed per-second rate (`STABILITY_FEE`,
  set at deployment, capped at 10% a year; the deploy script uses 2%). The
  interest is minted to the contract as the **surplus**. Anyone can buy surplus
  mUSD with ETH at the oracle price through `buy_surplus()`, which is how the
  extra mUSD that borrowers owe as interest reaches the market. The ETH paid
  goes to the `reserve`.
- **Liquidation:** any position below 150% can be liquidated. The liquidator
  repays mUSD and receives 110% of it in ETH (a 10% bonus). They repay only
  what brings the position back to 150%, so the borrower keeps the rest of
  their ETH.
- **Bad debt:** if a position's ETH is worth less than 110% of its debt, the
  liquidator repays what the ETH covers at 110% and takes all of it; the rest
  of the debt is written off as `bad_debt`. The surplus absorbs bad debt
  automatically. What it can't absorb, anyone can retire with
  `cover_bad_debt(amount)`, which burns their mUSD for ETH from the reserve at
  the oracle price.
- **Redemptions:** anyone can swap mUSD for $1 of ETH per mUSD from any
  healthy position with `redeem(user, amount)`, less a 0.5% fee that stays with
  the borrower. This puts a hard floor under the peg. The redeemer picks the
  position: sorting positions by risk on-chain (as Liquity does) costs too much
  for a contract this small, so any healthy position can be redeemed against.
- **Token:** ERC-20 + EIP-2612 permit, 18 decimals.

| Function | Description |
| --- | --- |
| `deposit()` / plain ETH transfer | Lock `msg.value` ETH as collateral |
| `mint(amount)` | Mint mUSD against your collateral (ratio ≥ 150%) |
| `burn(amount)` | Burn mUSD to repay your debt |
| `withdraw(amount)` | Withdraw ETH (ratio must stay ≥ 150%) |
| `liquidate(user, max_repay)` | Repay up to `max_repay` of `user`'s debt for 110% of it in ETH (ratio < 150%) |
| `redeem(user, amount)` | Burn `amount` mUSD of `user`'s debt for $1 of their ETH each, less 0.5% (ratio ≥ 150%) |
| `cover_bad_debt(amount)` | Burn `amount` mUSD of bad debt for its value in reserve ETH |
| `buy_surplus()` | Buy surplus mUSD with the sent ETH at the oracle price |
| `collat_ratio(user)` | 1e18-scaled collateral ratio (`1.5e18` = 150%) |
| `collateral(user)` / `debt(user)` | Position state (`debt` includes interest) |
| `surplus()` / `reserve()` / `bad_debt()` | Protocol-held mUSD (unsold interest), ETH (from surplus sales) and unbacked mUSD |

## Quickstart

```bash
mox compile        # compile
mox test           # run the test suite
mox run deploy     # deploy with a mock $2000 oracle on pyevm
```

The ETH/USD feed is the `eth_usd_price_feed` named contract in `moccasin.toml`.
Local networks (pyevm, anvil) deploy `tests/mocks/mock_aggregator.vy`; live
networks use the Chainlink feed address pinned there and refuse to deploy a mock.

```bash
mox run deploy --network sepolia --fork             # dry run against a Sepolia fork
mox run deploy --network sepolia --account <name>   # live deploy + Etherscan verification
```

Each live network sets `oracle_timeout` under `[networks.<name>.extra_data]`,
and L2s pin a `sequencer_uptime_feed` contract (the script refuses to deploy to
Arbitrum without one).

| Network | Feed heartbeat | `oracle_timeout` | Sequencer feed |
| --- | --- | --- | --- |
| Ethereum mainnet | 3600s | 4500s | — |
| Sepolia | 3600s | 4500s | — |
| Arbitrum One | 1755s | 2400s | `0xFdB631F5EE196F0ed6FAa767959853A9F217697D` |

Before deploying, the script checks that the feed is a contract, reports at most
18 decimals and has a fresh, positive answer, and that the sequencer (if any) is
up and past its grace period. After deploying, it reads the contract back to
confirm its parameters. Verification needs `ETHERSCAN_API_KEY` in `.env`, and
mainnet also needs `MAINNET_RPC_URL`.

## Tests

| Directory | Contents |
| --- | --- |
| `tests/unitary/ministable/` | One file per behavior: deposit, mint, burn, withdraw, liquidate, redeem, stability fee, oracle, collateral ratio, ERC-20, permit |
| `tests/integration/` | Multi-step position lifecycles (open/close, rescue, liquidation with bought mUSD) |
| `tests/fuzz/` | Hypothesis: exact mint/withdraw bounds, and a stateful model of interest, liquidations, bad debt, surplus and redemptions checking solvency invariants |
| `tests/mocks/` | Mock Chainlink feed and a contract position holder (ETH rejection, reentrancy) |

```bash
mox test tests/unitary   # fast unit tests only
mox test tests/fuzz      # property + stateful fuzzing (~45s)
FUZZ_EXAMPLES=1000 mox test tests/fuzz   # deeper stateful run (~10 min)
```

The stateful model checks after every step that:

- every position, balance, the rate index, surplus, reserve and bad debt match
  an independent reference model;
- total debt plus bad debt equals mUSD supply (plus interest not yet minted),
  with rounding only ever in the protocol's favour;
- the ETH the contract holds equals total collateral plus the reserve, and no
  ETH is created or destroyed;
- a liquidation not capped by `max_repay` leaves the position at 150% or more,
  and a redemption never lowers the redeemed position's ratio.

## Status

ministable has not been audited. Mainnet and Arbitrum are configured (with
`prompt_live = true`), but don't deploy there before an outside review of the
frozen code, such as a competitive audit.
