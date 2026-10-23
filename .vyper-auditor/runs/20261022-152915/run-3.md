<!--RUN pass=3 agents=12/12-->

All twelve specialties completed. Pass 3 ran after the project folder moved from `ministable/` to `ministable/core/`. No `.vy` file changed after the frozen SHA d3b1d80 (HEAD 74ccec5 changes only README.md, moccasin.toml and script/), so the frozen source is still valid.

Completeness: 16 unique (file, function) in raw, 11 covered in final, 5 rejected with reasons.

Gate notes:
- `modules/cdp.vy._liquidate` solvent-position-bad-debt: nine specialties (1, 2, 3, 4, 5, 7, 8, 10, 11) raised it as a FINDING. It stays at 75. The comment above `_liquidate` (cdp.vy:850-854) documents this behavior, so the team must decide whether it is a defect. All proposed fixes are one of two options. (a) `repay = min(d, value // PRECISION)` sets repay to the full collateral value below 100%, so it removes the bonus for underwater positions. That fix is unsafe. (b) `repay = d` when `value >= d * PRECISION` removes the write-off, but the bonus then drops to zero just above 100% and jumps to 10% just below it. No safe minimal fix is verified.
- `modules/cdp.vy._liquidate` coarse-collateral-zero-seize: agents 1 and 5 raised it as a FINDING, and agent 10 as a LEAD. The fix from agent 5 (`assert seized > 0`) is refuted, because it makes the liquidation revert and leaves the unhealthy position open. The fix from agent 1 (round `repay` up to a whole collateral unit) can push `repay` above `max_repay` or `d`, so it needs more than a minimal change. The verified fix stays `collateral_decimals >= 6`.
- `modules/cdp.vy._cover_bad_debt` zero-fee-oracle-swap: agent 3 raised it as a FINDING and agent 11 as a LEAD. It keeps 75 as a cross-contract echo of the `_buy_surplus` finding.
- `modules/cdp_erc20.vy.liquidate` zero-amount-transfer-revert (agent 9) and token-pause-blocks-liquidation (agent 3) have different triggers, so they keep separate labels.
- REJECTED `modules/erc20.vy.__module__` dead-owner-role (agent 2): Gate 4. No code path reads `owner`. This is the same issue that pass 1 rejected as orphaned-owner-role.
- REJECTED `modules/cdp.vy.surplus` view-omits-pending-accrual (agent 5): Gate 4. The only result is a revert of the buyer's own call.
- REJECTED `modules/cdp.vy._repay` zero-share-partial-repay (agents 7, 8): Gate 3. Each call moves less than 1 wei-USD, so gas costs more than the gain.
- REJECTED `modules/cdp.vy._accrue` debt-supply-rounding-drift (agent 10): Gate 3. The gap is wei-level, and no actor gains from it.
- REJECTED `modules/cdp.vy.mint` no-liquidation-buffer (agent 11): Gate 4. The harm is the intended liquidation bonus on a very small repay.
- REJECTED in covered functions: `_cover_bad_debt` accrue-shifts-exact-amount (agent 4, Gate 4: only the caller's own call reverts), and `_buy_surplus` unsettled-donated-surplus (agent 8, Gate 4: only the donor loses, and the buyer pays the oracle price).

<!--F key=modules-cdp-vy|-liquidate|coarse-collateral-zero-seize conf=80 kind=FINDING agents=1,5,10-->

[80] **Liquidators receive zero collateral for coarse high-price collateral**

`modules/cdp.vy._liquidate` · Confidence: 80

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

<!--/F-->

<!--F key=modules-cdp-vy|-buy-surplus|zero-fee-oracle-swap conf=75 kind=FINDING agents=3,11-->

[75] **Buyers take the oracle lag from the surplus**

`modules/cdp.vy._buy_surplus` · Confidence: 75

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

<!--/F-->

<!--F key=modules-cdp-vy|-cover-bad-debt|zero-fee-oracle-swap conf=75 kind=FINDING agents=3,11-->

[75] **Callers take reserve collateral at the oracle lag**

`modules/cdp.vy._cover_bad_debt` · Confidence: 75

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

<!--/F-->

<!--F key=modules-cdp-vy|-liquidate|solvent-position-bad-debt conf=75 kind=FINDING agents=1,2,3,4,5,7,8,10,11-->

[75] **Liquidation books bad debt on positions that cover their debt**

`modules/cdp.vy._liquidate` · Confidence: 75

**Description**
A liquidator takes all the collateral of a position worth 100–110% of its debt for value/1.1 mUSD, so the protocol books avoidable bad debt.

**Proof**
The branch test `if value >= LIQUIDATION_PENALTY * d:` (cdp.vy:869) sends every position with d <= value < 1.1·d to the else branch. There the code sets `repay = value // LIQUIDATION_PENALTY`, `seized = c` and `written_off = d - repay` (cdp.vy:884-890).

Trace (agents 1, 2, 4, 5, 7, 10, 11): c·p = $1050 and d = 1000e18, so value = 1050e36 < 1.1e18 · 1000e18 = 1100e36, and the else branch runs. repay = 954.545e18, seized = c (worth $1050), and written_off = 45.45e18 goes to `bad_debt`. `_settle` burns that amount from the surplus, or it stays as unbacked mUSD. Trace (agent 8): c = 1 ETH at $2000 and d = 1900e18 (105.3%) give written_off = 81.82e18. Trace (agent 3): at 109%, a borrower who liquidates their own position from a second address pays 990.9 mUSD for $1090 of collateral, which is $9.09 better than a normal repay. The loss is up to 9.09% of the debt (at value = d).

The position must pass the 110–150% band without a liquidation, which needs a price gap, an oracle pause or no active liquidator. The comment above `_liquidate` (cdp.vy:850-854) describes this behavior, so it can be intended. Nine specialties raised it independently in this pass.

**Fix**
No minimal safe fix is verified. The fix most agents proposed, `repay = min(d, value // PRECISION)`, sets repay to the full collateral value below 100%. That removes the bonus there and leaves underwater positions open, so it is unsafe. The other option, `repay = d` when `value >= d * PRECISION`, removes the write-off in [d, 1.1·d). With it, the bonus drops to zero just above 100% and jumps to 10% just below, so liquidators have a reason to wait. Any change needs a bonus that changes smoothly near 100%. The team must decide whether the fixed 110% bonus takes priority.

<!--/F-->

<!--F key=modules-cdp-vy|-redeem|redemption-oracle-lag-extraction kind=LEAD agents=3-->

- **Redeemers take borrower collateral when the oracle lag exceeds the fee** — `modules/cdp.vy._redeem` — Code smells: the 0.5% `REDEMPTION_FEE` equals the mainnet ETH/USD deviation threshold, and the redeemer picks the position and the time — Unverified: the deviation thresholds of the Sonic S/USD and Monad MON/USD feeds.

<!--/F-->

<!--F key=modules-cdp-vy|-buy-surplus|stranded-reserve kind=LEAD agents=3-->

- **No account can withdraw the reserve unless bad debt appears** — `modules/cdp.vy._buy_surplus` — Code smells: `self.reserve += paid` is the only inflow, and `_cover_bad_debt` is the only outflow. No owner function exists in ministable.vy or factory.vy — Unverified: whether the design intends the reserve as a permanent insurance fund.

<!--/F-->

<!--F key=modules-cdp-vy|-buy-surplus|coarse-surplus-unbuyable kind=LEAD agents=1-->

- **Buyers cannot buy a surplus residue smaller than one collateral unit** — `modules/cdp.vy._buy_surplus` — Code smells: `bought = paid * self._price() // PRECISION` moves in steps of `p / 1e18` per unit, and `assert bought <= erc20.balanceOf[self]` rejects a purchase above the surplus. For a 0-decimal token at $1000, up to 999 mUSD of surplus cannot be bought — Unverified: whether a deployment uses such a token. The `collateral_decimals >= 6` fix also removes this case.

<!--/F-->

<!--F key=modules-cdp-vy|-price|immutable-oracle-no-fallback kind=LEAD agents=3-->

- **A retired feed makes every price-based function fail forever** — `modules/cdp.vy._price` — Code smells: `ORACLE` is immutable and has no fallback, and the age check reverts mint, withdraw with debt, liquidate, redeem, buy_surplus and cover_bad_debt. `burn` and `deposit` still work — Unverified: whether Chainlink retires or pauses a pinned feed during the deployment.

<!--/F-->

<!--F key=modules-cdp-vy|-withdraw|oracle-dependent-withdraw-lock kind=LEAD agents=3-->

- **An oracle outage locks surplus collateral for every borrower with debt** — `modules/cdp.vy._withdraw` — Code smells: `_collat_ratio` calls `_price()` when debt is more than zero — Unverified: the length of real feed and sequencer outages. A borrower can `burn` all debt first and then withdraw.

<!--/F-->

<!--F key=modules-cdp-vy|-rate-index|caller-driven-compounding kind=LEAD agents=1-->

- **Callers can make the stability fee compound every block** — `modules/cdp.vy._rate_index` — Code smells: the index adds simple interest since `last_accrual`, and `mint(0)` lets any caller start a new interval, so borrowers pay about 3.821% in place of the configured 3.75% a year — Unverified: whether the team treats `STABILITY_FEE` as a nominal rate that compounds.

<!--/F-->

<!--F key=modules-cdp-vy|burn|no-full-repay-path kind=LEAD agents=4-->

- **Borrowers cannot close a position unless the burn lands in the predicted second** — `modules/cdp.vy.burn` — Code smells: `_repay` clears all shares only when `amount == d` and reverts when `amount > d`, and `debt()` grows every second, so `burn(debt(user))` mined one block late leaves a small debt — Unverified: the impact beyond dust. At 3.75% and 1000 mUSD, a 12 s delay leaves about 1.4e13 wei of debt. Integrators that close and then withdraw in one transaction get a revert.

<!--/F-->

<!--F key=modules-cdp-erc20-vy|-push|fee-on-transfer-outflow kind=LEAD agents=3,6-->

- **The module measures inflows but trusts outflows** — `modules/cdp_erc20.vy._push` — Code smells: `_pull` credits the measured balance increase, but `_push` sends `amount` and the callers subtract only `amount` from `collateral`/`reserve`. A token that charges its fee to the sender takes more than the books show — Unverified: whether such a token is ever listed. Only tests/mocks/cdp_erc20_harness.vy hosts this module.

<!--/F-->

<!--F key=modules-cdp-erc20-vy|liquidate|token-pause-blocks-liquidation kind=LEAD agents=3-->

- **A paused collateral token makes every liquidation fail** — `modules/cdp_erc20.vy.liquidate` — Code smells: `self._push(msg.sender, seized)` reverts while the token is paused or the liquidator is blacklisted — Unverified: which collateral token a production host lists.

<!--/F-->

<!--F key=modules-cdp-erc20-vy|liquidate|zero-amount-transfer-revert kind=LEAD agents=9-->

- **A token that rejects zero transfers makes liquidation revert when nothing is seized** — `modules/cdp_erc20.vy.liquidate` — Code smells: `_push(msg.sender, seized)` has no `if seized > 0` guard, and `seized` floors to 0 on the coarse-collateral path. `redeem` and `cover_bad_debt` push amounts that can also floor to 0 — Unverified: that a listed token both rejects zero transfers (for example BNB on Ethereum) and is coarse enough for `seized` to floor to 0.

<!--/F-->

<!--F key=src-ministable-vy|-init-|oracle-timeout-below-heartbeat kind=LEAD agents=12-->

- **The Arbitrum oracle timeout may be shorter than the feed heartbeat** — `src/ministable.vy.__init__` — Code smells: moccasin.toml sets `oracle_timeout = 2400  # 1755s heartbeat + 645s` for the Arbitrum ETH/USD feed `0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612`, and `ORACLE_TIMEOUT` is immutable. If the feed is quiet for longer, every price-based function reverts — Unverified: the real heartbeat of that feed on data.chain.link (the agent remembers 86400 s with a 0.05% deviation), and the Monad MON/USD heartbeat.

<!--/F-->
