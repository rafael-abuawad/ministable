<!--RUN pass=2 agents=12/12-->

All twelve specialties completed.

Completeness: 10 unique (file, function) in raw, 10 covered in final, 0 rejected with reasons.

Gate notes:
- `modules/cdp.vy._cover_bad_debt` zero-fee-oracle-swap (agents 2, 3, 4, 5, 6, 8, 11, 12) has the same root cause as the confirmed `_buy_surplus` finding. It is promoted at 75 as a cross-contract echo, with a verified fix.
- `modules/cdp.vy._liquidate` solvent-position-bad-debt: agent 1 raised it as a FINDING, and agents 3, 7, 8, 9 and 12 raised it as a LEAD. It is promoted at 75 by multi-agent convergence. The fix agent 7 proposed (`repay = max(value // LIQUIDATION_PENALTY, min(d, value // PRECISION))`) is refuted: below 100% it sets repay to the full collateral value, so it removes the liquidation bonus for underwater positions. No minimal safe fix is verified. The Fix block says this.
- Agent 1's `coarse-collateral-zero-seize` LEAD (an 8-decimal WBTC loss of less than one unit) is merged into the FINDING.
- `_rate_index` caller-driven-fee-compounding (agent 10) and `_accrue` caller-driven-compounding (agent 12) describe one class at two functions. They keep separate keys under the label `caller-driven-compounding`.

<!--F key=modules-cdp-vy|-liquidate|coarse-collateral-zero-seize conf=80 kind=FINDING agents=1,3,9,10-->

[80] **Liquidators receive zero collateral for coarse high-price collateral**

`modules/cdp.vy._liquidate` · Confidence: 80

**Description**
A liquidator burns mUSD and gets zero units of a coarse high-price collateral, so no liquidator acts until the position is below 110%.

**Proof**
Seam: boundary (few-decimal, high-price collateral) × precision (`seized` floors to whole base units) × invariant (an unhealthy position is liquidated back to 150% at a 10% bonus).

`cdp.__init__` accepts any `collateral_decimals <= 18` (cdp.vy:767). In the if branch, `repay` is capped at the amount that returns the position to 150% (`min(min((needed + step - 1) // step, d), max_repay)`, cdp.vy:879), and `seized = min(repay * LIQUIDATION_PENALTY // p, c)` (cdp.vy:881) floors.

Trace (agent 3): the collateral has 0 decimals and costs $100,000, with an 8-decimal feed (answer = 1e13). PRICE_SCALE = 1e28, so p = 1e41. Position: c = 3, d = 200_001e18 (ratio 1.49999). value = 3e41. needed ≈ 4.5e36, so repay ≈ 1.125e19 (11.25 mUSD). seized = 1.125e19 * 1.1e18 // 1e41 = 0. Seizing one unit needs repay >= 90_909 mUSD, which needs a ratio of 1.318 or lower for this d. Positions between about 1.32 and 1.5 therefore stay open. At repay = 100_000 mUSD, seized = 1 unit ($100,000), so the liquidator gets no bonus.

Trace (agent 10): 0 decimals at $1000 gives p = 1e39. Every repay below 909.09e18 seizes 0. A repay of 1500e18 seizes 1 unit ($1000) for $1500 of mUSD.

Route: `cdp_erc20.liquidate` → `cdp._liquidate` → `erc20._burn(msg.sender, repay)` → `_push(msg.sender, seized)`. A token that reverts on a zero transfer also makes the call revert. `cdp_native` is not affected (18 decimals).

**Fix**

```diff
     assert collateral_decimals <= 18 # dev: [cdp] unsupported collateral decimals
+    # @dev Coarse units floor `seized` to zero in `_liquidate`.
+    assert collateral_decimals >= 6 # dev: [cdp] unsupported collateral decimals
```

With 6 or more decimals, one unit of a $100,000 asset is worth $0.10 or less, so the floor loss is dust. `cdp_native` passes 18 and is not changed. Tests that use a 0-decimal collateral market must expect a deploy revert.

<!--/F-->

<!--F key=modules-cdp-vy|-buy-surplus|zero-fee-oracle-swap conf=75 kind=FINDING agents=3,4,8,11-->

[75] **Buyers take the oracle lag from the surplus**

`modules/cdp.vy._buy_surplus` · Confidence: 75

**Description**
Any caller buys surplus mUSD at an old oracle price with no fee, so the caller keeps the price lag that the protocol loses.

**Proof**
`bought: uint256 = paid * self._price() // PRECISION` (cdp.vy:944) has no spread, but `_redeem` applies `REDEMPTION_FEE` to the same oracle-priced swap (cdp.vy:910). Chainlink updates only on a deviation threshold or a heartbeat (moccasin.toml: mainnet heartbeat 3600 s, `oracle_timeout` 4500), so the answer can lag the market by up to the threshold.

Trace (agent 4, mainnet ETH/USD, 0.5% threshold): the oracle reports 3000e8 and the market is at 2985.1 (-0.497%, so no update). The attacker sends 33.333e18 wei (worth $99,503) to `buy_surplus()` and receives 100_000e18 mUSD of surplus. The attacker gains about $497, and the reserve holds collateral worth less than the mUSD it sold. On mainnet, the attacker can also back-run a pending feed update from the public mempool. The attack repeats in every lag window.

Route: `cdp_native.buy_surplus` (payable) / `cdp_erc20.buy_surplus` → `cdp._buy_surplus`. Any caller can call it.

**Fix**

```diff
-    bought: uint256 = paid * self._price() // PRECISION
+    bought: uint256 = paid * self._price() // PRECISION * (PRECISION - REDEMPTION_FEE) // PRECISION
```

The change only lowers `bought`, so `assert bought > 0` and `assert bought <= erc20.balanceOf[self]` still hold, and no new revert path appears. Use a separate, larger constant for feeds whose deviation threshold is above 0.5%.

<!--/F-->

<!--F key=modules-cdp-vy|-cover-bad-debt|zero-fee-oracle-swap conf=75 kind=FINDING agents=2,3,4,5,6,8,11,12-->

[75] **Callers take reserve collateral at the oracle lag**

`modules/cdp.vy._cover_bad_debt` · Confidence: 75

**Description**
Any mUSD holder burns bad debt at an old, low oracle price with no fee, so the holder takes more reserve collateral than the mUSD is worth.

**Proof**
`paid: uint256 = amount * PRECISION // self._price()` (cdp.vy:927) pays reserve collateral at the raw oracle price. `_redeem` performs the same mUSD-to-collateral swap with `amount * (PRECISION - REDEMPTION_FEE) // self._price()` (cdp.vy:910). This is the root cause of the `_buy_surplus` finding, in the other direction.

Trace (agent 4, mainnet ETH/USD): bad_debt = 100_000e18, the oracle reports 3000e8, reserve >= 33.4e18 wei, and the market is at 3014.9 (+0.497%, so no update). The attacker buys 100_000 mUSD at $1 or less and calls `cover_bad_debt(100_000e18)`: paid = 1e23 * 1e18 // 3000e18 = 33.333e18 wei, worth $100,497. The reserve that backs other mUSD holders loses about $497. Agent 8 shows a two-leg version: buy surplus while the oracle is above the market, then cover bad debt after the update.

Precondition: `bad_debt > 0` and `reserve > 0` at the same time. `_settle` uses the surplus first, so this state needs bad debt larger than the surplus after an earlier `buy_surplus` filled the reserve. The state is specific but reachable through normal use.

Route: `cdp_native.cover_bad_debt` (`raw_call(msg.sender, b"", value=paid)`) / `cdp_erc20.cover_bad_debt` (`_push`) → `cdp._cover_bad_debt`. Any caller can call it.

**Fix**

```diff
-    paid: uint256 = amount * PRECISION // self._price()
+    paid: uint256 = amount * (PRECISION - REDEMPTION_FEE) // self._price()
```

The change only lowers `paid`, so `assert paid <= self.reserve` still holds and the accounting (`bad_debt -= amount`, `reserve -= paid`) is unchanged. The unpaid 0.5% stays in the reserve.

<!--/F-->

<!--F key=modules-cdp-vy|-liquidate|solvent-position-bad-debt conf=75 kind=FINDING agents=1,3,7,8,9,12-->

[75] **Liquidation books bad debt on positions that cover their debt**

`modules/cdp.vy._liquidate` · Confidence: 75

**Description**
A liquidator takes all the collateral of a position worth 100–110% of its debt for value/1.1 mUSD, so the protocol books avoidable bad debt.

**Proof**
The branch test `if value >= LIQUIDATION_PENALTY * d:` (cdp.vy:869) sends every position with d <= value < 1.1·d to the else branch. There, `repay = value // LIQUIDATION_PENALTY`, `seized = c` and `written_off = d - repay` (cdp.vy:884-890) are applied. The module NatSpec says only "Debt that a position's collateral cannot cover becomes bad debt".

Native trace (agent 7): c = 1.05e18 wei, ETH at $1000 (p = 1000e18), d = 1000e18. value = 1050e36 < 1100e36, so the code takes the else branch. repay = 954.54e18, seized = 1.05e18 (worth $1050), and written_off = 45.45e18 goes to `bad_debt`. `_settle` burns that amount from the protocol surplus, or it stays as unbacked mUSD. The borrower can liquidate their own position from a second address: they burn 954.54 of the 1000 mUSD they minted, take back all $1050, and keep 45.45 mUSD. The loss is up to 9.09% of the debt (at value = d). The position must pass the 110–150% band without a liquidation, which needs a price gap, an oracle pause, or no active liquidators. Six specialties raised this issue independently, so it is promoted at 75.

**Fix**
No minimal safe fix is verified. One proposed fix, `repay = max(value // LIQUIDATION_PENALTY, min(d, value // PRECISION))`, sets repay to the full collateral value below 100%. That removes the bonus there and leaves underwater positions open, so it is unsafe. Another option is `repay = d` when `value >= d * PRECISION`. It removes the write-off in [d, 1.1·d), but the bonus then drops to zero just above 100% and jumps to 10% just below, so liquidators have a reason to wait. Any change needs a bonus that varies smoothly near 100%, and the team must decide whether the fixed 110% bonus takes priority.

<!--/F-->

<!--F key=modules-cdp-vy|-liquidate|all-or-nothing-liquidation kind=LEAD agents=1,3,8-->

- **Underwater liquidation needs the full repay from one balance** — `modules/cdp.vy._liquidate` — Code smells: the else branch asserts `max_repay >= repay` with `repay = value // LIQUIDATION_PENALTY`, mUSD has no flash mint, and a borrower can deposit 1 wei first to make a tight `max_repay` revert — Unverified: whether mUSD liquidity is deep enough for the largest underwater positions.

<!--/F-->

<!--F key=modules-cdp-vy|-redeem|redemption-oracle-lag-extraction kind=LEAD agents=3,4-->

- **Redeemers take borrower collateral when the oracle lag exceeds the fee** — `modules/cdp.vy._redeem` — Code smells: the 0.5% `REDEMPTION_FEE` equals the mainnet ETH/USD deviation threshold, and the redeemer picks the position and the time — Unverified: how often the lag on each chain's feed is more than 0.5%.

<!--/F-->

<!--F key=modules-cdp-vy|-withdraw|oracle-dependent-withdraw-lock kind=LEAD agents=3-->

- **An oracle outage locks surplus collateral for every borrower with debt** — `modules/cdp.vy._withdraw` — Code smells: `_withdraw` calls `_collat_ratio`, which calls `_price()` and `_check_sequencer()` when debt is more than zero — Unverified: the length of real feed and sequencer outages. `burn` still works.

<!--/F-->

<!--F key=modules-cdp-vy|-price|immutable-oracle-no-fallback kind=LEAD agents=3-->

- **A retired feed makes every price-based function fail forever** — `modules/cdp.vy._price` — Code smells: `ORACLE` is immutable and has no fallback, and liquidate, redeem, buy_surplus, cover_bad_debt, mint and withdraw with debt all read the price — Unverified: whether Chainlink retires or pauses a pinned feed during the deployment.

<!--/F-->

<!--F key=modules-cdp-vy|-buy-surplus|stranded-reserve kind=LEAD agents=5-->

- **No account can withdraw the reserve unless bad debt appears** — `modules/cdp.vy._buy_surplus` — Code smells: `self.reserve += paid` is the only inflow, and `_cover_bad_debt` is the only outflow. No sweep or owner function exists, so all stability-fee revenue that buyers convert stays locked as collateral — Unverified: whether the design intends the reserve as a permanent insurance fund.

<!--/F-->

<!--F key=modules-cdp-vy|-rate-index|caller-driven-compounding kind=LEAD agents=10-->

- **Callers can make the stability fee compound every block** — `modules/cdp.vy._rate_index` — Code smells: the index adds simple interest since `last_accrual`, and each accrual starts from the new index, so per-block accrual gives about 10.52% a year at the cap that the code calls 10% — Unverified: whether the 10% cap is a hard promise to borrowers or an approximate target.

<!--/F-->

<!--F key=modules-cdp-vy|-accrue|caller-driven-compounding kind=LEAD agents=12-->

- **Any caller compounds interest with mint(0)** — `modules/cdp.vy._accrue` — Code smells: `mint(0)` from a caller with no debt passes every check and calls `_accrue`, so borrowers pay 3.82% in place of the configured 3.75% a year — Unverified: whether the team treats `STABILITY_FEE` as a nominal rate that compounds.

<!--/F-->

<!--F key=modules-cdp-erc20-vy|-push|fee-on-transfer-outflow kind=LEAD agents=12-->

- **The module measures inflows but trusts outflows** — `modules/cdp_erc20.vy._push` — Code smells: `_pull` credits the measured balance increase, but `_push` does not measure the balance drop. A token that charges the fee to the sender takes more tokens from the contract than the books show, so the last withdrawer finds the contract short — Unverified: whether a token of this kind is ever listed. No production host uses cdp_erc20 yet.

<!--/F-->

<!--F key=modules-cdp-erc20-vy|liquidate|token-pause-blocks-liquidation kind=LEAD agents=12-->

- **A paused collateral token makes every liquidation fail** — `modules/cdp_erc20.vy.liquidate` — Code smells: `liquidate` must complete `_push(msg.sender, seized)`, while `mint` values the frozen collateral at the oracle price and does not touch the token — Unverified: which collateral token is listed and whether it can pause transfers.

<!--/F-->
