<!--RUN pass=2 agents=10/12-->

Lost coverage: agent 11 (trust-gap) and agent 12 (flow-gap) ended early on an API rate-limit error (HTTP 429, session limit). They were not retried. Their gap-hunter seams were not re-walked in this pass.

Completeness: 5 unique (file, function) in raw, 4 covered in final, 1 rejected with reasons.

Gate notes for this pass:

- `modules/erc20.vy.transfer` · unlocked-module-export (agent 4) — REJECTED at Gate 1. `modules/erc20.vy` sets `# pragma nonreentrancy off`, so exported `transfer`, `transferFrom`, `approve`, and `permit` take no lock. Both host callbacks (`withdraw` line 192 and `liquidate` line 206) run after every storage write. A re-entrant call sees final `debt`, `collateral`, balances, and `totalSupply`. Agents 4, 5, 6, 8, and 9 traced this independently and found no state to exploit.
- `src/ministable.vy._price` · future-updated-at-underflow (agent 1) — REJECTED at Gate 2. This repeats the pass-1 refutation: a Chainlink aggregator never reports `updatedAt` later than the current block timestamp. Agents 3, 4, 6, 8, and 9 dropped it on the same grounds.
- `src/ministable.vy.liquidate` · full-collateral-seizure (agent 9 FINDING, plus 1–8 and 10 as LEAD) — kept as a LEAD. The trace is correct, but the contract NatSpec specifies that "the liquidator burns the whole debt and receives all of the position's ETH". The harm is specified behaviour, not a deviation the code introduces. The zero buffer between the mint and liquidation thresholds is noted in the lead.
- `src/ministable.vy.mint` · no-minimum-debt (agents 1, 4, 7, 8, 9, 10; agent 5 filed it under `liquidate`) — kept as a LEAD. Labels `dust-position-unliquidatable`, `no-minimum-debt-dust-position`, and `missing-min-debt` are folded into the most frequent label. Pass 1 rejected the dust variant at Gate 4. This pass adds a realistic non-dust size: a debt of about $10 leaves under $5 of surplus, below the cost of L1 gas. Harm per position stays bounded and does not compound, and no attacker profits. This stays a Gate 4 demotion with no promotion: the total amount of bad debt is not shown to be material.
- `src/ministable.vy._price` · immutable-oracle-no-fallback (agents 5, 7) and oracle-revert-blocks-liquidation (agent 9) — merged under `immutable-oracle-no-fallback` as a LEAD. The defect is distinct from the timeout margin: `ORACLE` is immutable with no setter, so a retired feed blocks `liquidate`, `mint`, and borrower `withdraw` permanently.
- `src/ministable.vy.liquidate` · unliquidatable-bad-debt — ten agents filed it as a FINDING. The gating is the same as in pass 1: no concrete guard refutes the trace. The price gap through 100% remains the unverified market link (partial path −20, specific state −10 = 70), and convergence promotes it to 75.

<!--F key=src-ministable-vy|liquidate|unliquidatable-bad-debt conf=75 kind=FINDING agents=1,2,3,4,5,6,7,8,9,10-->

[75] **No liquidator closes a position whose collateral is worth less than its debt**

`src/ministable.vy.liquidate` · Confidence: 75

**Description**
When the ETH price falls below a 100% collateral ratio, `liquidate` costs more mUSD than it pays in ETH, so no one calls it and mUSD holders keep unbacked debt.

**Proof**
`liquidate` (src/ministable.vy:197-206) only closes whole positions: it burns the full `d` from the caller (`erc20._burn(msg.sender, d)`, line 204) and pays exactly `c` (`raw_call(msg.sender, b"", value=c)`, line 206). No other function reduces another user's `debt`. `burn` only reduces `debt[msg.sender]`. The contract has no reserve, no stability pool, and no socialisation path.

Trace (agents 3, 7, 8):

1. Alice deposits 1 ETH at `answer = 3000e8` and calls `mint(2000e18)`. ratio = 3000e18 * 1e18 // 2000e18 = 1.5e18, so the mint passes.
2. The ETH price falls to $1500 in one feed update, or while `_price` reverts during an oracle stall. ratio = 1500e18 * 1e18 // 2000e18 = 0.75e18 < 1.5e18, so the `liquidate` guard passes.
3. A liquidator must burn 2000 mUSD (about $2000) to receive 1 ETH ($1500), a loss of $500. No rational caller acts.
4. `totalSupply == Σ debt` still holds (agents 5, 8, and 10 confirmed it across `mint`, `burn`, and `liquidate`). But Σ(collateral · price) < totalSupply: 2000 mUSD keeps only $1500 of backing, and Alice keeps the 2000 mUSD.

Unverified link: the price must move from ≥150% to <100% before any liquidator acts. This needs a fast crash, congestion, or an oracle stall (see the `oracle-timeout-equals-heartbeat` and `immutable-oracle-no-fallback` leads). Market conditions trigger it, not a privileged actor. The contract has no recovery once it happens.

**Fix**

No safe minimal patch exists. Closing positions below 100% needs a protocol-level loss absorber, which is a design change. Options: (a) a `liquidate(user, amount)` with a close factor and a capped bonus, so that liquidation happens earlier and in parts; and (b) a reserve or stability pool, funded from liquidation surplus, that absorbs `d - c * price` when a position goes underwater, or socialises it across borrowers. Option (a) alone lowers the chance of the gap but does not remove it.

<!--/F-->

<!--F key=src-ministable-vy|liquidate|full-collateral-seizure kind=LEAD agents=1,2,3,4,5,6,7,8,9,10-->

- **A borrower at the mint limit loses all surplus ETH after a 1e-8 USD price tick** — `src/ministable.vy.liquidate` — Code smells: `mint`/`withdraw` accept `ratio >= MIN_COLLAT_RATIO` and `liquidate` accepts `ratio < MIN_COLLAT_RATIO` on the same `_collat_ratio`, with no buffer between them. `liquidate` pays all of `c`. With 1.5 ETH and 2000e18 debt at `answer = 2000e8`, a move to `199999999999` gives ratio 1.4999999999925e18, and the liquidator burns 2000 mUSD for about $3000 of ETH (agent 9) — Unverified: the NatSpec documents full seizure, so whether the protocol accepts a surplus loss of up to 0.5 × d for the healthiest liquidatable positions needs owner intent.

<!--/F-->

<!--F key=src-ministable-vy|liquidate|all-or-nothing-liquidation kind=LEAD agents=1,2,3,4,5,6,7,8,9,10-->

- **Liquidation needs the caller to hold the whole debt in one balance** — `src/ministable.vy.liquidate` — Code smells: `erc20._burn(msg.sender, d)` with no `amount` parameter, no flash mint, and no repay-on-behalf path. A liquidator must hold `d` mUSD already, or lock about 1.5 × d of ETH to mint it — Unverified: mUSD market depth compared with the largest position. Liquidation through `mint` stays possible, so this is a capital barrier and not a hard block.

<!--/F-->

<!--F key=src-ministable-vy|-price|hardcoded-oracle-decimals kind=LEAD agents=1,2,3,4,5,6,7,8,9-->

- **The price scaling assumes an 8-decimal feed** — `src/ministable.vy._price` — Code smells: `return convert(answer, uint256) * 10**10`, and `IAggregatorV3.decimals()` is declared but never called. An 18-decimal feed scales collateral value by 1e10, so a 1-wei deposit mints about 1.3e13 mUSD (agent 1) — Unverified: the decimals of the deployed feed. Chainlink ETH/USD feeds use 8 decimals, and the code comment documents that assumption.

<!--/F-->

<!--F key=src-ministable-vy|-price|oracle-timeout-equals-heartbeat kind=LEAD agents=1,2,3,5,6,7-->

- **The oracle timeout equals the feed heartbeat and has no margin** — `src/ministable.vy._price` — Code smells: `ORACLE_TIMEOUT = 3600` equals the mainnet ETH/USD heartbeat. A late heartbeat round makes `liquidate`, `mint`, and borrower `withdraw` revert. On a chain whose feed has an 86400 s heartbeat, they revert for most of each calm day — Unverified: the heartbeat of the target chain's feed and its normal update delay.

<!--/F-->

<!--F key=src-ministable-vy|-price|immutable-oracle-no-fallback kind=LEAD agents=5,7,9-->

- **A retired or paused feed blocks liquidation permanently** — `src/ministable.vy._price` — Code smells: `ORACLE: public(immutable(IAggregatorV3))` has no setter and no fallback, and Vyper `staticcall` cannot be caught. If the feed stops updating, `_price` always reverts, so `liquidate`, `mint`, and borrower `withdraw` revert forever, and only `burn` and debt-free `withdraw` work — Unverified: whether the deployed feed is retired or migrated while positions are open, and how far the price moves during an outage.

<!--/F-->

<!--F key=src-ministable-vy|-price|missing-sequencer-uptime-check kind=LEAD agents=2,3,5,6-->

- **The price read has no L2 sequencer uptime check** — `src/ministable.vy._price` — Code smells: no sequencer uptime feed and no grace period, while `moccasin.toml` configures `zksync-sepolia` — Unverified: whether production deploys to an L2 that has a sequencer uptime feed.

<!--/F-->

<!--F key=src-ministable-vy|-price|chainlink-min-answer-clamp kind=LEAD agents=2,3,5,6-->

- **The price read does not reject answers at the aggregator min/max bounds** — `src/ministable.vy._price` — Code smells: `assert answer > 0` is the only bound — Unverified: whether the target aggregator still enforces `minAnswer`/`maxAnswer`.

<!--/F-->

<!--F key=src-ministable-vy|-init-|unguarded-oracle-binding kind=LEAD agents=2,3,5-->

- **The only deploy script binds the immutable oracle to a mock that any caller can write** — `src/ministable.vy.__init__` — Code smells: `script/deploy.py` deploys `tests/mocks/mock_aggregator.vy`, whose `set_answer`/`set_updated_at` have no caller check, and passes it as `ORACLE`. `__init__` accepts it unchecked — Unverified: whether this script deploys to a network where real value is at risk (`moccasin.toml` lists sepolia and zksync-sepolia).

<!--/F-->

<!--F key=src-ministable-vy|mint|no-minimum-debt kind=LEAD agents=1,4,5,7,8,9,10-->

- **Borrowers can open positions too small to liquidate at a profit** — `src/ministable.vy.mint` — Code smells: `mint` and `burn` enforce no minimum debt, and the liquidator surplus `c * p - d` is under 0.5 × d with no fixed incentive. At about $3.6 of L1 gas, a $10 debt at a 1.49 ratio leaves about $4.9, and smaller positions leave less than the cost of gas (agent 7) — Unverified: the gas cost on the target chain, and how much total small-position debt forms in practice. Each position costs its creator 150% collateral, so no attacker profits.

<!--/F-->
