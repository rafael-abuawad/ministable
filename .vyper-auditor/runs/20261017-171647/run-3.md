<!--RUN pass=3 agents=12/12-->

All twelve specialties completed.

Source drift notice: during the scan, edits appeared in the working tree (timestamps 17:54–17:57, after the 17:16 freeze): `src/ministable.vy`, `modules/erc20.vy`, `script/deploy.py`, `tests/conftest.py`, and `tests/fuzz/test_solvency_invariants.py`. They change `__init__` to take `name_`, `symbol_`, and `decimals_`, and move `name`/`symbol`/`decimals` into `modules/erc20.vy`. This report covers only the frozen source at c8d66b8. Agents 4, 9, and 11 read the edited `script/deploy.py` and reported a four-argument call against a one-argument constructor. That observation concerns the working tree, not the frozen source, and is discarded. Agent 3 ran its proof of concept in `/tmp/poc3`, outside the repository.

Completeness: 6 unique (file, function) in raw, 5 covered in final, 1 rejected with reasons.

Gate notes for this pass:

- `src/ministable.vy.__module__` · inert-owner-role (agent 2) — REJECTED. `ow.__init__()` makes the deployer the owner, but no function checks `ow.owner`, and `transfer_ownership`/`renounce_ownership` are not exported. A role with no power has no exploit path. The real consequence, that no one can replace the oracle, is already covered by `immutable-oracle-no-fallback`. The misleading NatSpec at `modules/erc20.vy` (references to `is_minter`) is a documentation issue, which the judging rules exclude.
- `src/ministable.vy._price` · future-timestamp underflow (agents 1, 7, 9, 12, under various labels) — REJECTED at Gate 2 for the third time: a live Chainlink feed never reports `updatedAt` later than the block timestamp.
- `src/ministable.vy.liquidate` · full-collateral-seizure (agents 5 and 10 FINDING, all others LEAD) — kept as a LEAD for the same reason as in earlier passes: the NatSpec specifies full seizure.
- `src/ministable.vy.withdraw` · oracle-dependent-withdraw-lock (agent 11) — new LEAD. It is distinct from `immutable-oracle-no-fallback` in `_price` because the harm is the asymmetric lock-out of borrowers who have debt.
- `src/ministable.vy.liquidate` · unliquidatable-bad-debt — all twelve agents filed it as a FINDING. Agent 3 reproduced the code trace with Titanoboa on the frozen source: `collat_ratio` 1500375093773443360 at $2000 becomes 900225056264066016 at $1200, and the liquidator's net is −$133. The market gap remains the unverified link, and convergence holds the confidence at 75.

<!--F key=src-ministable-vy|liquidate|unliquidatable-bad-debt conf=75 kind=FINDING agents=1,2,3,4,5,6,7,8,9,10,11,12-->

[75] **No liquidator closes a position whose collateral is worth less than its debt**

`src/ministable.vy.liquidate` · Confidence: 75

**Description**
When the ETH price falls below a 100% collateral ratio, `liquidate` costs more mUSD than it pays in ETH, so no one calls it and mUSD holders keep unbacked debt.

**Proof**
`liquidate` (src/ministable.vy:197-206) only closes whole positions:

```vyper
assert self._collat_ratio(user) < MIN_COLLAT_RATIO, "ministable: position healthy"
d: uint256 = self.debt[user]
c: uint256 = self.collateral[user]
self.debt[user] = 0
self.collateral[user] = 0
erc20._burn(msg.sender, d)
...
raw_call(msg.sender, b"", value=c)
```

The guard admits every ratio below 1.5e18, including ratios below 1e18. The caller always pays `d` and always receives `c`. No other function reduces another user's debt: `burn` (line 181) only reduces `debt[msg.sender]`. The contract has no reserve, no stability pool, and no socialisation path.

Reproduced trace (agent 3, Titanoboa on the frozen source, run outside the repository):

1. B deposits 1e18 wei and mints 1333e18 at `answer = 2000e8`. `collat_ratio(B) = 1500375093773443360` ≥ 1.5e18.
2. The answer falls to 1200e8. `collat_ratio(B) = 900225056264066016` < 1.5e18, so `liquidate(B)` is allowed.
3. Liquidator L burns 1333 mUSD and receives 1 ETH worth $1200, a net loss of $133. No rational liquidator calls it.
4. `totalSupply == Σ debt` holds (agents 5, 8, and 10), but 1333e18 mUSD keeps only $1200 of ETH backing. The gap grows with every further price drop.

Unverified link: the price must move from ≥150% to <100% before any liquidator acts (fast crash, congestion, or an oracle stall; see the `oracle-timeout-equals-heartbeat` and `immutable-oracle-no-fallback` leads). No privileged action is needed, and the contract has no recovery once it happens.

**Fix**

No safe minimal patch exists. Closing positions below 100% needs a protocol-level loss absorber, which is a design change. Options: (a) a `liquidate(user, amount)` with a close factor and a capped bonus, so that positions are closed earlier and in parts; and (b) a reserve or stability pool, funded from liquidation surplus, that absorbs `d - c * price` when a position goes underwater, or socialises it across borrowers. Option (a) alone lowers the chance of the gap but does not remove it.

<!--/F-->

<!--F key=src-ministable-vy|liquidate|full-collateral-seizure kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,11,12-->

- **A borrower at the mint limit loses all surplus ETH after a 1e-8 USD price tick** — `src/ministable.vy.liquidate` — Code smells: `mint` (line 173) passes at `ratio >= MIN_COLLAT_RATIO` and `liquidate` (line 199) opens at `ratio < MIN_COLLAT_RATIO`, with no buffer between them. Line 206 sends all of `c`. With 1e18 wei and debt 1333333333333333333333 at `answer = 2000e8`, a move to `199999999999` gives ratio 1499999999992500000000, and the liquidator burns 1333.33 mUSD for about $2000 of ETH, a borrower loss of $666.67 (agent 10) — Unverified: the NatSpec documents full seizure, so the open question is whether the protocol accepts a surplus loss of up to 0.5 × d for the healthiest liquidatable positions.

<!--/F-->

<!--F key=src-ministable-vy|liquidate|all-or-nothing-liquidation kind=LEAD agents=1,2,3,4,5,6,7,8,9,10,12-->

- **Liquidation needs the caller to hold the whole debt in one balance** — `src/ministable.vy.liquidate` — Code smells: `erc20._burn(msg.sender, d)` with no `amount` parameter and no flash mint. A flash loan of ETH cannot fund the trade: minting `d` locks 1.5 × d of ETH value, but liquidating a position below 150% returns less than 1.5 × d (agent 3) — Unverified: mUSD market depth and liquidator capital compared with the largest position. Liquidation through `mint` stays possible, so this is a capital barrier and not a hard block.

<!--/F-->

<!--F key=src-ministable-vy|-price|hardcoded-oracle-decimals kind=LEAD agents=3,4,7,9-->

- **The price scaling assumes an 8-decimal feed** — `src/ministable.vy._price` — Code smells: `convert(answer, uint256) * 10**10`, and `IAggregatorV3.decimals()` is never called — Unverified: the decimals of the deployed feed. Chainlink ETH/USD feeds use 8 decimals, and the code comment documents that assumption.

<!--/F-->

<!--F key=src-ministable-vy|-price|immutable-oracle-no-fallback kind=LEAD agents=3,4,7-->

- **A retired or paused feed blocks liquidation permanently** — `src/ministable.vy._price` — Code smells: `ORACLE: public(immutable(IAggregatorV3))` has no setter and no fallback. The deployer-owned `ow` role checks nothing, so no admin path exists either (agent 2). Any revert in `_price` blocks `liquidate`, `mint`, and borrower `withdraw` — Unverified: the deprecation or pause policy of the deployed feed on the target network.

<!--/F-->

<!--F key=src-ministable-vy|-price|oracle-timeout-equals-heartbeat kind=LEAD agents=4,7-->

- **The oracle timeout equals the feed heartbeat and has no margin** — `src/ministable.vy._price` — Code smells: `ORACLE_TIMEOUT = 3600` equals the mainnet ETH/USD heartbeat. A late round reverts `liquidate`, `mint`, and borrower `withdraw` — Unverified: the target chain and the feed heartbeat.

<!--/F-->

<!--F key=src-ministable-vy|-price|missing-sequencer-uptime-check kind=LEAD agents=4,7-->

- **The price read has no L2 sequencer uptime check** — `src/ministable.vy._price` — Code smells: no sequencer uptime feed and no grace period — Unverified: whether the target chain is an L2.

<!--/F-->

<!--F key=src-ministable-vy|-price|chainlink-min-answer-clamp kind=LEAD agents=4,7-->

- **The price read does not reject answers at the aggregator min/max bounds** — `src/ministable.vy._price` — Code smells: `answer > 0` is the only bound — Unverified: whether the deployed aggregator still enforces `minAnswer`/`maxAnswer`.

<!--/F-->

<!--F key=src-ministable-vy|-init-|unguarded-oracle-binding kind=LEAD agents=2,4,7-->

- **The only deploy script binds the immutable oracle to a mock that any caller can write** — `src/ministable.vy.__init__` — Code smells: `script/deploy.py` (frozen version) deploys `tests/mocks/mock_aggregator.vy` and passes it as `ORACLE`. The mock's `set_answer`/`set_updated_at` have no caller check, so any caller can set the price to 1 and liquidate every position — Unverified: whether this script runs on a network where real value is at risk. `ORACLE` is immutable, so a bad binding is permanent.

<!--/F-->

<!--F key=src-ministable-vy|withdraw|oracle-dependent-withdraw-lock kind=LEAD agents=11-->

- **An oracle outage locks surplus ETH for every borrower with debt** — `src/ministable.vy.withdraw` — Code smells: `_collat_ratio` returns early when `d == 0` (line 242), but reads `_price` for any debt above zero, even far above 150%. While the feed is stale, `mint` also reverts, so mUSD supply is frozen at `Σ debt`. A borrower must buy back the full debt on the market to `burn` before `withdraw` succeeds — Unverified: how long a feed outage lasts on the target chain, and whether market holders sell mUSD during it.

<!--/F-->

<!--F key=src-ministable-vy|mint|no-minimum-debt kind=LEAD agents=3,4,5,6,7,8,12-->

- **Borrowers can open positions too small to liquidate at a profit** — `src/ministable.vy.mint` — Code smells: `mint` accepts any `amount`, and no minimum debt or collateral exists. The liquidator surplus `c * p - d` is under 0.5 × d — Unverified: the gas cost on the target chain, and whether total small-position debt becomes material. Each position costs its creator 150% collateral, so no attacker profits.

<!--/F-->
