<!--RUN pass=1 agents=12/12-->

Completeness: 4 unique (file, function) in raw, 3 covered in final, 1 rejected with reasons.

All twelve specialties completed. Gate notes for this pass:

- `src/ministable.vy.mint` · dust-position-unliquidatable (agent 6) — REJECTED at Gate 4: each dust position costs its creator 150% collateral, and the bad debt is bounded dust that does not compound. Agent 10 dropped the same issue on these grounds.
- `src/ministable.vy._price` · oracle-timestamp-underflow (agents 5, 6, future `updated_at`) — REJECTED at Gate 2: a Chainlink aggregator sets `updatedAt` to the block timestamp of the update transaction, so `updated_at > block.timestamp` cannot occur on a live feed. The checked subtraction reverts in any case. No loss path exists.
- `src/ministable.vy.liquidate` · unliquidatable-concentrated-debt / all-or-nothing-liquidation (agents 7, 12, FINDING) — DEMOTED at Gate 1. The claim says no caller other than the whale can hold `d` mUSD. `mint` has no access control, so a liquidator can deposit ETH, mint `d` new mUSD at 150%, and liquidate. In agent 12's example (whale debt 133,000 mUSD and ETH at $1900), a liquidator deposits about 105 ETH, mints 133,000 mUSD, burns it in `liquidate`, and receives 100 ETH worth $190,000. Liquidation is therefore possible. What remains is a capital barrier: no partial path and no flash mint. This is kept as a lead under the canonical label `all-or-nothing-liquidation`, merged with agent 6's `liquidation-requires-full-debt`.
- `src/ministable.vy._price` · hardcoded-oracle-decimals (agents 1–10) — kept as a LEAD, not promoted. The vulnerable state exists only if the deployer binds a feed that does not use 8 decimals. Line 234 documents "8-decimal feed", and `IAggregatorV3.decimals` documents "8 for USD feeds". All Chainlink ETH/USD feeds use 8 decimals. A deployer who chose another feed would be acting against documented intent, and no unprivileged amplifier exists. Agreement between agents does not create reachability.
- `src/ministable.vy._price` · oracle-timeout-equals-heartbeat (agents 3, 5, 8, 9, 10, 11, 12) — kept as a LEAD. On mainnet the claimed harm (liquidations blocked during a price crash) conflicts with the feed mechanism: a deviation of 0.5% or more starts a new round and refreshes `updated_at`. A stale window therefore occurs mostly in calm markets. The sustained-DoS variant needs a deployment on a chain whose feed heartbeat is longer than 3600 s. That deployment is not verified.
- `src/ministable.vy.liquidate` · full-collateral-seizure (agents 3, 5, 7, 11) — kept as a LEAD. The contract NatSpec documents that the liquidator "receives all of the position's ETH", so the size of the penalty is specified behaviour. The zero buffer between the mint limit and the liquidation limit is not documented.
- `src/ministable.vy.liquidate` · unliquidatable-bad-debt (agents 1, 3, 4, 5, 6, 8, 9, 10, 11, 12) — PROMOTED to 75 by multi-agent convergence. Agent 9 filed it as a FINDING. The others filed it as a LEAD because a market price gap through 100% is the unverified link. No concrete guard refutes the path.

<!--F key=src-ministable-vy|liquidate|unliquidatable-bad-debt conf=75 kind=FINDING agents=1,3,4,5,6,8,9,10,11,12-->

[75] **No liquidator closes a position whose collateral is worth less than its debt**

`src/ministable.vy.liquidate` · Confidence: 75

**Description**
When the ETH price falls below a 100% collateral ratio, `liquidate` costs more mUSD than it pays in ETH, so no one calls it and mUSD holders keep unbacked debt.

**Proof**
`liquidate` (src/ministable.vy:197-206) always burns the full debt from the caller and pays out the full collateral:

```vyper
d: uint256 = self.debt[user]
c: uint256 = self.collateral[user]
...
erc20._burn(msg.sender, d)
...
raw_call(msg.sender, b"", value=c)
```

The function has no repay amount, no payout cap, no bonus, no reserve, and no path for bad debt. `burn` reduces only `debt[msg.sender]`, so no third party can repay part of a position.

Trace (agent 9):

1. A user deposits 1 ETH at `answer = 2000e8` and calls `mint(1333e18)`. ratio = 2000e18 * 1e18 // 1333e18 = 1.5003e18 ≥ 1.5e18, so the mint passes.
2. The ETH price falls to $1200 before any liquidation runs. ratio = 1200e18 * 1e18 // 1333e18 ≈ 0.90e18 < 1.5e18, so `liquidate` is allowed.
3. A liquidator must burn 1333 mUSD (about $1333) to receive 1 ETH ($1200), a loss of $133. No rational liquidator calls it.
4. The position stays open. Since `totalSupply == Σ debt` (mint, burn, and liquidate change both by the same amount), 1333 mUSD in circulation has only $1200 of ETH behind it, and the gap grows as the price falls.

Unverified link: a price move from ≥150% to <100% must happen before any liquidator acts. This can happen in a fast crash, during congestion, or during an oracle stall. Unprivileged market conditions trigger it, not an attacker, and the contract has no backstop when it happens.

**Fix**

No safe minimal patch exists. The protocol needs a bad-debt mechanism, which is a design change and not a line edit. Options: (a) a `liquidate(user, amount)` with a close factor and a fixed bonus, so that positions are closed earlier and in parts; and (b) a reserve or stability pool, funded from liquidation surplus, that absorbs debt when `c * price < d`. Option (a) alone lowers the chance of the gap but does not remove it.

<!--/F-->

<!--F key=src-ministable-vy|-price|hardcoded-oracle-decimals kind=LEAD agents=1,2,3,4,5,6,7,8,9,10-->

- **The price scaling assumes an 8-decimal feed** — `src/ministable.vy._price` — Code smells: `return convert(answer, uint256) * 10**10`, `__init__` accepts any `oracle`, and `IAggregatorV3.decimals()` is declared but never called. With an 18-decimal feed the price is 1e10 times too high, so 1 ETH supports about 1.33e31 mUSD instead of 1.33e21 — Unverified: the production feed address and its decimals. `script/deploy.py` deploys only the 8-decimal mock. Check the deployed feed, or add `assert staticcall oracle.decimals() == 8` in `__init__`.

<!--/F-->

<!--F key=src-ministable-vy|-init-|unguarded-oracle-binding kind=LEAD agents=2,4-->

- **The only deploy script binds the immutable oracle to a mock that any caller can write** — `src/ministable.vy.__init__` — Code smells: `script/deploy.py` calls `mock_aggregator.deploy(ETH_USD_PRICE)` with no network branch, and `tests/mocks/mock_aggregator.vy` `set_answer` and `set_updated_at` have no caller check. `ORACLE` is immutable. On such a deployment any caller can call `set_answer(2**200)`, mint about 1e52 mUSD for 1 wei, then call `set_answer(1)` and liquidate every position for its ETH — Unverified: whether any deployment with value runs this script on sepolia, zksync-sepolia, or mainnet. Check that a production deploy path binds a real Chainlink feed.

<!--/F-->

<!--F key=src-ministable-vy|-price|oracle-timeout-equals-heartbeat kind=LEAD agents=3,5,8,9,10,11,12-->

- **The oracle timeout equals the feed heartbeat and has no margin** — `src/ministable.vy._price` — Code smells: `ORACLE_TIMEOUT = 3600` equals the mainnet ETH/USD heartbeat, and `ORACLE` is immutable with no fallback. `liquidate`, `mint`, and `withdraw` with debt revert while the round is stale. On a chain whose ETH/USD feed has an 86400 s heartbeat (`moccasin.toml` targets zkSync), these functions revert for most of each calm day, and a deprecated feed blocks them forever — Unverified: the target chain and the feed heartbeat. On mainnet, deviation-triggered rounds refresh `updated_at` during large moves, so a stale window mostly occurs while the price is stable.

<!--/F-->

<!--F key=src-ministable-vy|-price|missing-sequencer-uptime-check kind=LEAD agents=6,9-->

- **The price read has no L2 sequencer uptime check** — `src/ministable.vy._price` — Code smells: `_price` checks only `answer > 0` and the age of the answer. There is no sequencer uptime feed and no grace period, although `moccasin.toml` configures `zksync-sepolia` (`is_zksync = true`) — Unverified: whether production deploys to an L2 that has a Chainlink sequencer uptime feed. If it does, users can mint or liquidate at a pre-downtime price after the sequencer restarts.

<!--/F-->

<!--F key=src-ministable-vy|-price|chainlink-min-answer-clamp kind=LEAD agents=9-->

- **The price read does not reject answers at the aggregator min/max bounds** — `src/ministable.vy._price` — Code smells: any `answer > 0` is accepted, with no comparison to `minAnswer`/`maxAnswer` — Unverified: whether the deployed aggregator still has active circuit-breaker bounds that the ETH price can reach. Most current ETH/USD feeds no longer enforce them.

<!--/F-->

<!--F key=src-ministable-vy|liquidate|all-or-nothing-liquidation kind=LEAD agents=3,6,7,12-->

- **Liquidation needs the caller to hold the whole debt in one balance** — `src/ministable.vy.liquidate` — Code smells: `erc20._burn(msg.sender, d)` with no repay amount and no flash mint. If a borrower keeps most of the supply, other holders cannot burn `d` from existing mUSD. A liquidator must first lock about 1.5 × d of ETH in a new position to mint `d` — Unverified: whether liquidator capital is enough to close a large position before it falls below 100%. Liquidation is still possible through `mint`, which refutes the claim that the position cannot be liquidated at all.

<!--/F-->

<!--F key=src-ministable-vy|liquidate|full-collateral-seizure kind=LEAD agents=3,5,7,11-->

- **A borrower at the mint limit loses all surplus ETH after a 1e-8 USD price tick** — `src/ministable.vy.liquidate` — Code smells: `mint` passes at `ratio >= MIN_COLLAT_RATIO` and `liquidate` opens at `ratio < MIN_COLLAT_RATIO`, with no buffer between them. The liquidator receives all of `c`, so a borrower who deposits 1.5 ETH at $2000 and mints 2000 mUSD loses about $1000 when the answer moves from 2000e8 to 199999999999 — Unverified: the NatSpec documents full liquidation, so the size of the penalty may be intended. The zero buffer, and a penalty that is largest for the healthiest liquidatable positions, are not documented.

<!--/F-->
