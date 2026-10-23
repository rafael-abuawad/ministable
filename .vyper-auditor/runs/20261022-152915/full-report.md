# 🔐 Security Review — ministable (Vyper)

---

## Scope

|  |  |
| --- | --- |
| **Mode** | default |
| **Files reviewed** | `src/factory.vy` · `src/ministable.vy` · `modules/erc20.vy`<br>`modules/cdp.vy` · `modules/cdp_native.vy` · `modules/cdp_erc20.vy` |
| **Compiler context** | All six files pin "# pragma version ~=0.4.3" (>=0.4.3,<0.5.0). Local compiler is vyper 0.4.3+commit.bff19ea2 (~/.local/bin/vyper, used by mox). No vyper pin in pyproject/uv.lock; deployed bytecode version not verified. nonreentrancy pragma: on in ministable.vy, cdp.vy, cdp_native.vy, cdp_erc20.vy; off in factory.vy and erc20.vy. |
| **Confidence threshold (1-100)** | 75 |
| **Passes** | 3 (pass 1 ran 5/12 agents) |
| **Memory** | 11 records before this scan · 31 after · `d3b1d80` |

---

## Findings

[80] **1. Liquidators receive zero collateral for coarse high-price collateral**

`modules/cdp.vy._liquidate` · Confidence: 80 · [agents: 1,5,10] · seen in 3/3 runs · NEW

**Description**
A liquidator burns mUSD and gets zero units of a coarse, high-price collateral, so no liquidator closes small shortfalls.

**Proof**
`cdp.__init__` accepts any `collateral_decimals <= 18` (cdp.vy:767). In the if branch, `seized = min(repay * LIQUIDATION_PENALTY // p, c)` (cdp.vy:881) floors to whole base units, and `erc20._burn(msg.sender, repay)` (cdp.vy:893) still runs.

Trace (agent 5): a 0-decimal token at $1 with an 8-decimal feed. PRICE_SCALE = 10**(36-8-0) = 1e28, so p = 1e36. For repay = 1e17 (0.1 mUSD), seized = 1e17 * 1.1e18 // 1e36 = 0. The liquidator burns 0.1 mUSD and receives nothing.

Trace (agent 10): 8-decimal WBTC at $60,000 gives p = 6e32. Every repay below 5.45e14 seizes 0. For WBTC this loss is dust. For 0-decimal, high-price collateral (earlier passes: $1000 to $100,000 a unit), the zero-seize band covers repays up to the value of one unit. Positions in that band stay open until the price falls far enough for one unit to be seized, or until the else branch runs below 110%.

Route: `cdp_erc20.liquidate` → `cdp._liquidate` → `erc20._burn` → `_push(msg.sender, seized)`. `cdp_native` is not affected, because its collateral has 18 decimals.

**Fix**

```diff
     assert collateral_decimals <= 18 # dev: [cdp] unsupported collateral decimals
+    # @dev Coarse units floor `seized` to zero in `_liquidate`.
+    assert collateral_decimals >= 6 # dev: [cdp] unsupported collateral decimals
```

With 6 or more decimals, one unit of a $100,000 asset is worth $0.10 or less, so the floor loss is dust. `cdp_native` passes 18 and does not change. Tests that use a 0-decimal collateral market must expect a deploy revert. An `assert seized > 0` is not safe: the liquidation then reverts and the unhealthy position stays open.

---

[75] **2. Buyers take the oracle lag from the surplus**

`modules/cdp.vy._buy_surplus` · Confidence: 75 · [agents: 3,11] · seen in 3/3 runs · NEW

**Description**
Any caller buys surplus mUSD at an old oracle price with no fee, so the caller keeps the price lag that the protocol loses.

**Proof**
`bought: uint256 = paid * self._price() // PRECISION` (cdp.vy:944) charges no spread. `_redeem` charges `REDEMPTION_FEE` for the same oracle-priced swap in the other direction (cdp.vy:910). Chainlink updates only after a deviation threshold or a heartbeat, so the answer can lag the market by up to that threshold.

Trace (agent 3, mainnet ETH/USD, 0.5% deviation): the market falls 0.49% and the oracle does not update. With p = 2000e18 and a surplus of 10,000e18, the buyer sends 5 ETH (worth $9,951 at market) and gets `5e18 * 2000e18 // 1e18 = 10,000e18` mUSD. The buyer gains $49, and the reserve keeps ETH that is overvalued by 0.49%. Trace (agent 11, Base ETH/USD, 0.15% deviation): the gain is about $15 for each 10,000 mUSD. The gain repeats each time interest refills the surplus.

Route: `cdp_native.buy_surplus` (payable) / `cdp_erc20.buy_surplus` → `cdp._buy_surplus`. Any caller can call it.

**Fix**

```diff
-    bought: uint256 = paid * self._price() // PRECISION
+    bought: uint256 = paid * self._price() // PRECISION * (PRECISION - REDEMPTION_FEE) // PRECISION
```

The change only lowers `bought`, so `assert bought > 0` and `assert bought <= erc20.balanceOf[self]` still hold, and no new revert path appears. Use a separate, larger constant for feeds whose deviation threshold is above 0.5%.

---

[75] **3. Callers take reserve collateral at the oracle lag**

`modules/cdp.vy._cover_bad_debt` · Confidence: 75 · [agents: 3,11] · seen in 2/3 runs · NEW

**Description**
Any mUSD holder burns bad debt at an old, low oracle price with no fee, so the holder takes more reserve collateral than the mUSD is worth.

**Proof**
`paid: uint256 = amount * PRECISION // self._price()` (cdp.vy:927) pays reserve collateral at the raw oracle price. `_redeem` performs the same swap with `amount * (PRECISION - REDEMPTION_FEE) // self._price()` (cdp.vy:910).

Trace (agent 3): the market is 0.49% above the oracle (p = 2000e18, market $2009.8). With bad_debt = 1,000e18 and reserve = 1e18 wei, the caller buys 1000 mUSD at the market for $1000 and calls `cover_bad_debt(1000e18)`. Then `paid = 1000e18 * 1e18 // 2000e18 = 0.5e18` wei, worth $1004.9. The caller gains $4.9 (0.49%), and the reserve loses the same amount.

Precondition (agent 11): `bad_debt > 0` and `reserve > 0` at the same time. `_settle` uses the surplus first, so the reserve must be filled by earlier `buy_surplus` calls. The state is specific but reachable through normal use. This is the same root cause as the `_buy_surplus` finding, so it is promoted at 75 as a cross-contract echo.

Route: `cdp_native.cover_bad_debt` (`raw_call(msg.sender, b"", value=paid)`) / `cdp_erc20.cover_bad_debt` (`_push`) → `cdp._cover_bad_debt`. Any caller can call it.

**Fix**

```diff
-    paid: uint256 = amount * PRECISION // self._price()
+    paid: uint256 = amount * (PRECISION - REDEMPTION_FEE) // self._price()
```

The change only lowers `paid`, so `assert paid <= self.reserve` still holds and the accounting (`bad_debt -= amount`, `reserve -= paid`) does not change. The unpaid 0.5% stays in the reserve.

---

[75] **4. Liquidation books bad debt on positions that cover their debt**

`modules/cdp.vy._liquidate` · Confidence: 75 · [agents: 1,2,3,4,5,7,8,10,11] · seen in 3/3 runs · NEW

**Description**
A liquidator takes all the collateral of a position worth 100–110% of its debt for value/1.1 mUSD, so the protocol books avoidable bad debt.

**Proof**
The branch test `if value >= LIQUIDATION_PENALTY * d:` (cdp.vy:869) sends every position with d <= value < 1.1·d to the else branch. There the code sets `repay = value // LIQUIDATION_PENALTY`, `seized = c` and `written_off = d - repay` (cdp.vy:884-890).

Trace (agents 1, 2, 4, 5, 7, 10, 11): c·p = $1050 and d = 1000e18, so value = 1050e36 < 1.1e18 · 1000e18 = 1100e36, and the else branch runs. repay = 954.545e18, seized = c (worth $1050), and written_off = 45.45e18 goes to `bad_debt`. `_settle` burns that amount from the surplus, or it stays as unbacked mUSD. Trace (agent 8): c = 1 ETH at $2000 and d = 1900e18 (105.3%) give written_off = 81.82e18. Trace (agent 3): at 109%, a borrower who liquidates their own position from a second address pays 990.9 mUSD for $1090 of collateral, which is $9.09 better than a normal repay. The loss is up to 9.09% of the debt (at value = d).

The position must pass the 110–150% band without a liquidation, which needs a price gap, an oracle pause or no active liquidator. The comment above `_liquidate` (cdp.vy:850-854) describes this behavior, so it can be intended. Nine specialties raised it independently in this pass.

**Fix**
No minimal safe fix is verified. The fix most agents proposed, `repay = min(d, value // PRECISION)`, sets repay to the full collateral value below 100%. That removes the bonus there and leaves underwater positions open, so it is unsafe. The other option, `repay = d` when `value >= d * PRECISION`, removes the write-off in [d, 1.1·d). With it, the bonus drops to zero just above 100% and jumps to 10% just below, so liquidators have a reason to wait. Any change needs a bonus that changes smoothly near 100%. The team must decide whether the fixed 110% bonus takes priority.

---

Findings List

| # | Confidence | Title |
|---|---|---|
| 1 | [80] | Liquidators receive zero collateral for coarse high-price collateral |
| 2 | [75] | Buyers take the oracle lag from the surplus |
| 3 | [75] | Callers take reserve collateral at the oracle lag |
| 4 | [75] | Liquidation books bad debt on positions that cover their debt |

---

## Leads

_Vulnerability trails with concrete code smells where the full exploit path could not be completed in one analysis pass. These are not false positives — they are high-signal leads for manual review. Not scored._

- **The module measures inflows but trusts outflows** — `modules/cdp_erc20.vy._push` · seen in 2/3 runs · NEW · [agents: 3,6] — Code smells: `_pull` credits the measured balance increase, but `_push` sends `amount` and the callers subtract only `amount` from `collateral`/`reserve`. A token that charges its fee to the sender takes more than the books show — Unverified: whether such a token is ever listed. Only tests/mocks/cdp_erc20_harness.vy hosts this module.
- **A paused collateral token makes every liquidation fail** — `modules/cdp_erc20.vy.liquidate` · seen in 2/3 runs · NEW · [agents: 3] — Code smells: `self._push(msg.sender, seized)` reverts while the token is paused or the liquidator is blacklisted — Unverified: which collateral token a production host lists.
- **A token that rejects zero transfers makes liquidation revert when nothing is seized** — `modules/cdp_erc20.vy.liquidate` · seen in 1/3 runs · NEW · [agents: 9] — Code smells: `_push(msg.sender, seized)` has no `if seized > 0` guard, and `seized` floors to 0 on the coarse-collateral path. `redeem` and `cover_bad_debt` push amounts that can also floor to 0 — Unverified: that a listed token both rejects zero transfers (for example BNB on Ethereum) and is coarse enough for `seized` to floor to 0.
- **Any caller compounds interest with mint(0)** — `modules/cdp.vy._accrue` · seen in 1/3 runs · NEW · [agents: 12] — Code smells: `mint(0)` from a caller with no debt passes every check and calls `_accrue`, so borrowers pay 3.82% in place of the configured 3.75% a year — Unverified: whether the team treats `STABILITY_FEE` as a nominal rate that compounds.
- **Buyers cannot buy a surplus residue smaller than one collateral unit** — `modules/cdp.vy._buy_surplus` · seen in 1/3 runs · NEW · [agents: 1] — Code smells: `bought = paid * self._price() // PRECISION` moves in steps of `p / 1e18` per unit, and `assert bought <= erc20.balanceOf[self]` rejects a purchase above the surplus. For a 0-decimal token at $1000, up to 999 mUSD of surplus cannot be bought — Unverified: whether a deployment uses such a token. The `collateral_decimals >= 6` fix also removes this case.
- **No account can withdraw the reserve unless bad debt appears** — `modules/cdp.vy._buy_surplus` · seen in 2/3 runs · NEW · [agents: 3] — Code smells: `self.reserve += paid` is the only inflow, and `_cover_bad_debt` is the only outflow. No owner function exists in ministable.vy or factory.vy — Unverified: whether the design intends the reserve as a permanent insurance fund.
- **Underwater liquidation needs the full repay from one balance** — `modules/cdp.vy._liquidate` · seen in 2/3 runs · NEW · [agents: 1,3,8] — Code smells: the else branch asserts `max_repay >= repay` with `repay = value // LIQUIDATION_PENALTY`, mUSD has no flash mint, and a borrower can deposit 1 wei first to make a tight `max_repay` revert — Unverified: whether mUSD liquidity is deep enough for the largest underwater positions.
- **The price read accepts answers at the aggregator floor** — `modules/cdp.vy._price` · seen in 1/3 runs · NEW · [agents: 4] — Code smells: `assert answer > 0` and the age check are the only validation — Unverified: whether the deployed aggregators still have active minAnswer/maxAnswer bounds.
- **A retired feed makes every price-based function fail forever** — `modules/cdp.vy._price` · seen in 3/3 runs · NEW · [agents: 3] — Code smells: `ORACLE` is immutable and has no fallback, and the age check reverts mint, withdraw with debt, liquidate, redeem, buy_surplus and cover_bad_debt. `burn` and `deposit` still work — Unverified: whether Chainlink retires or pauses a pinned feed during the deployment.
- **Callers can make the stability fee compound every block** — `modules/cdp.vy._rate_index` · seen in 2/3 runs · NEW · [agents: 1] — Code smells: the index adds simple interest since `last_accrual`, and `mint(0)` lets any caller start a new interval, so borrowers pay about 3.821% in place of the configured 3.75% a year — Unverified: whether the team treats `STABILITY_FEE` as a nominal rate that compounds.
- **Redeemers take borrower collateral when the oracle lag exceeds the fee** — `modules/cdp.vy._redeem` · seen in 3/3 runs · NEW · [agents: 3] — Code smells: the 0.5% `REDEMPTION_FEE` equals the mainnet ETH/USD deviation threshold, and the redeemer picks the position and the time — Unverified: the deviation thresholds of the Sonic S/USD and Monad MON/USD feeds.
- **An oracle outage locks surplus collateral for every borrower with debt** — `modules/cdp.vy._withdraw` · seen in 3/3 runs · NEW · [agents: 3] — Code smells: `_collat_ratio` calls `_price()` when debt is more than zero — Unverified: the length of real feed and sequencer outages. A borrower can `burn` all debt first and then withdraw.
- **Borrowers cannot close a position unless the burn lands in the predicted second** — `modules/cdp.vy.burn` · seen in 1/3 runs · NEW · [agents: 4] — Code smells: `_repay` clears all shares only when `amount == d` and reverts when `amount > d`, and `debt()` grows every second, so `burn(debt(user))` mined one block late leaves a small debt — Unverified: the impact beyond dust. At 3.75% and 1000 mUSD, a 12 s delay leaves about 1.4e13 wei of debt. Integrators that close and then withdraw in one transaction get a revert.
- **Borrowers can open positions too small to liquidate at a profit** — `modules/cdp.vy.mint` · seen in 1/3 runs · NEW · [agents: 4] — Code smells: `mint` has no lower bound on the resulting debt — Unverified: the gas cost against the 10% bonus on the target chains.
- **The Arbitrum oracle timeout may be shorter than the feed heartbeat** — `src/ministable.vy.__init__` · seen in 1/3 runs · NEW · [agents: 12] — Code smells: moccasin.toml sets `oracle_timeout = 2400  # 1755s heartbeat + 645s` for the Arbitrum ETH/USD feed `0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612`, and `ORACLE_TIMEOUT` is immutable. If the feed is quiet for longer, every price-based function reverts — Unverified: the real heartbeat of that feed on data.chain.link (the agent remembers 86400 s with a 0.05% deviation), and the Monad MON/USD heartbeat.
- **The constructor accepts mUSD decimals other than 18** — `src/ministable.vy.__init__` · seen in 1/3 runs · NEW · [agents: 4,9,10] — Code smells: `decimals_` goes from `factory.deploy_ministable` to `erc20.__init__` with no check, but `cdp` treats 1e18 base units as $1 — Unverified: that the factory owner ever deploys with `decimals_ != 18`. The deploy script uses 18.

---

## Known from earlier scans

_Recorded by earlier scans of this repo, not raised again by this one. Not re-checked — a record here may be fixed, or may still be live and missed. `.vyper-auditor/memory.tsv`._

| Scans | Kind | Location | Title |
|---|---|---|---|
| 1 | LEAD | `src/ministable.vy.__init__` | The only deploy script binds the immutable oracle to a mock that any caller can  |
| 1 | LEAD | `src-ministable-vy.-price` | The price read does not reject answers at the aggregator min/max bounds |
| 1 | LEAD | `src-ministable-vy.-price` | The price scaling assumes an 8-decimal feed |
| 1 | LEAD | `src-ministable-vy.-price` | A retired or paused feed blocks liquidation permanently |
| 1 | LEAD | `src-ministable-vy.-price` | The price read has no L2 sequencer uptime check |
| 1 | LEAD | `src-ministable-vy.-price` | The oracle timeout equals the feed heartbeat and has no margin |
| 1 | LEAD | `src-ministable-vy.liquidate` | Liquidation needs the caller to hold the whole debt in one balance |
| 1 | LEAD | `src-ministable-vy.liquidate` | A borrower at the mint limit loses all surplus ETH after a 1e-8 USD price tick |
| 1 | FINDING | `src-ministable-vy.liquidate` | No liquidator closes a position whose collateral is worth less than its debt |
| 1 | LEAD | `src-ministable-vy.mint` | Borrowers can open positions too small to liquidate at a profit |
| 1 | LEAD | `src-ministable-vy.withdraw` | An oracle outage locks surplus ETH for every borrower with debt |

---

> ⚠️ This review was performed by an AI assistant. AI analysis can never verify the complete absence of vulnerabilities and no guarantee of security is given. Team security reviews, bug bounty programs, and on-chain monitoring are strongly recommended. For a consultation regarding your projects' security, visit [https://www.pashov.com](https://www.pashov.com)
