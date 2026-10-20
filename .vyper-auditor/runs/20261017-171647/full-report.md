# 🔐 Security Review — ministable (Vyper)

---

## Scope

|  |  |
| --- | --- |
| **Mode** | default |
| **Files reviewed** | `src/ministable.vy` · `modules/erc20.vy` |
| **Compiler context** | pragma ~=0.4.3 in both files; local vyper 0.4.3+commit.bff19ea2; snekmate 0.1.2; nonreentrancy pragma on in src/ministable.vy, off in modules/erc20.vy; deployed bytecode version not verified |
| **Confidence threshold (1-100)** | 75 |
| **Passes** | 3 (pass 2 ran 10/12 agents) |
| **Memory** | 0 records before this scan · 11 after · `c8d66b8` |

---

## Findings

[75] **1. No liquidator closes a position whose collateral is worth less than its debt**

`src/ministable.vy.liquidate` · Confidence: 75 · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] · seen in 3/3 runs · NEW

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

---

Findings List

| # | Confidence | Title |
|---|---|---|
| 1 | [75] | No liquidator closes a position whose collateral is worth less than its debt |

---

## Leads

_Vulnerability trails with concrete code smells where the full exploit path could not be completed in one analysis pass. These are not false positives — they are high-signal leads for manual review. Not scored._

- **The only deploy script binds the immutable oracle to a mock that any caller can write** — `src/ministable.vy.__init__` · seen in 3/3 runs · NEW · [agents: 2,4,7] — Code smells: `script/deploy.py` (frozen version) deploys `tests/mocks/mock_aggregator.vy` and passes it as `ORACLE`. The mock's `set_answer`/`set_updated_at` have no caller check, so any caller can set the price to 1 and liquidate every position — Unverified: whether this script runs on a network where real value is at risk. `ORACLE` is immutable, so a bad binding is permanent.
- **Liquidation needs the caller to hold the whole debt in one balance** — `src/ministable.vy.liquidate` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,12] — Code smells: `erc20._burn(msg.sender, d)` with no `amount` parameter and no flash mint. A flash loan of ETH cannot fund the trade: minting `d` locks 1.5 × d of ETH value, but liquidating a position below 150% returns less than 1.5 × d (agent 3) — Unverified: mUSD market depth and liquidator capital compared with the largest position. Liquidation through `mint` stays possible, so this is a capital barrier and not a hard block.
- **A borrower at the mint limit loses all surplus ETH after a 1e-8 USD price tick** — `src/ministable.vy.liquidate` · seen in 3/3 runs · NEW · [agents: 1,2,3,4,5,6,7,8,9,10,11,12] — Code smells: `mint` (line 173) passes at `ratio >= MIN_COLLAT_RATIO` and `liquidate` (line 199) opens at `ratio < MIN_COLLAT_RATIO`, with no buffer between them. Line 206 sends all of `c`. With 1e18 wei and debt 1333333333333333333333 at `answer = 2000e8`, a move to `199999999999` gives ratio 1499999999992500000000, and the liquidator burns 1333.33 mUSD for about $2000 of ETH, a borrower loss of $666.67 (agent 10) — Unverified: the NatSpec documents full seizure, so the open question is whether the protocol accepts a surplus loss of up to 0.5 × d for the healthiest liquidatable positions.
- **Borrowers can open positions too small to liquidate at a profit** — `src/ministable.vy.mint` · seen in 2/3 runs · NEW · [agents: 3,4,5,6,7,8,12] — Code smells: `mint` accepts any `amount`, and no minimum debt or collateral exists. The liquidator surplus `c * p - d` is under 0.5 × d — Unverified: the gas cost on the target chain, and whether total small-position debt becomes material. Each position costs its creator 150% collateral, so no attacker profits.
- **The price read does not reject answers at the aggregator min/max bounds** — `src/ministable.vy._price` · seen in 3/3 runs · NEW · [agents: 4,7] — Code smells: `answer > 0` is the only bound — Unverified: whether the deployed aggregator still enforces `minAnswer`/`maxAnswer`.
- **The price scaling assumes an 8-decimal feed** — `src/ministable.vy._price` · seen in 3/3 runs · NEW · [agents: 3,4,7,9] — Code smells: `convert(answer, uint256) * 10**10`, and `IAggregatorV3.decimals()` is never called — Unverified: the decimals of the deployed feed. Chainlink ETH/USD feeds use 8 decimals, and the code comment documents that assumption.
- **A retired or paused feed blocks liquidation permanently** — `src/ministable.vy._price` · seen in 2/3 runs · NEW · [agents: 3,4,7] — Code smells: `ORACLE: public(immutable(IAggregatorV3))` has no setter and no fallback. The deployer-owned `ow` role checks nothing, so no admin path exists either (agent 2). Any revert in `_price` blocks `liquidate`, `mint`, and borrower `withdraw` — Unverified: the deprecation or pause policy of the deployed feed on the target network.
- **The price read has no L2 sequencer uptime check** — `src/ministable.vy._price` · seen in 3/3 runs · NEW · [agents: 4,7] — Code smells: no sequencer uptime feed and no grace period — Unverified: whether the target chain is an L2.
- **The oracle timeout equals the feed heartbeat and has no margin** — `src/ministable.vy._price` · seen in 3/3 runs · NEW · [agents: 4,7] — Code smells: `ORACLE_TIMEOUT = 3600` equals the mainnet ETH/USD heartbeat. A late round reverts `liquidate`, `mint`, and borrower `withdraw` — Unverified: the target chain and the feed heartbeat.
- **An oracle outage locks surplus ETH for every borrower with debt** — `src/ministable.vy.withdraw` · seen in 1/3 runs · NEW · [agents: 11] — Code smells: `_collat_ratio` returns early when `d == 0` (line 242), but reads `_price` for any debt above zero, even far above 150%. While the feed is stale, `mint` also reverts, so mUSD supply is frozen at `Σ debt`. A borrower must buy back the full debt on the market to `burn` before `withdraw` succeeds — Unverified: how long a feed outage lasts on the target chain, and whether market holders sell mUSD during it.

---

> ⚠️ This review was performed by an AI assistant. AI analysis can never verify the complete absence of vulnerabilities and no guarantee of security is given. Team security reviews, bug bounty programs, and on-chain monitoring are strongly recommended. For a consultation regarding your projects' security, visit [https://www.pashov.com](https://www.pashov.com)
