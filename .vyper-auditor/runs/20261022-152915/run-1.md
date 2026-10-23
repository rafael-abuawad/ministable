<!--RUN pass=1 agents=5/12-->

Lost coverage: 7 of 12 specialties failed on an API session limit (HTTP 429) and were not retried: 1 math-precision, 5 invariant, 6 periphery, 7 first-principles, 8 asymmetry, 11 trust-gap, 12 flow-gap. Completed: 2 access-control, 3 economic-security, 4 execution-trace, 9 boundary, 10 numerical-gap.

Completeness: 8 unique (file, function) in raw, 7 covered in final, 1 rejected with reasons.

Gate notes:
- `modules/cdp.vy._liquidate` solvent-position-bad-debt (agent 3, raised as FINDING): demoted to LEAD. Gate 4: the else branch matches the Aave-style rule (the liquidator takes all collateral for collateral/bonus). The proposed fix moves the bonus jump from 110% to 100% and gives liquidators a reason to wait. This is a design tradeoff, not a proven defect.
- `modules/cdp.vy._liquidate` coarse-collateral-zero-seize (agent 10 FINDING) and coarse-collateral-unliquidatable (agent 9 LEAD) are one mechanism. They are merged under the shorter label.
- `modules/cdp.vy._buy_surplus` zero-fee-oracle-arbitrage (3), zero-fee-oracle-swap (4) and zero-spread-oracle-arbitrage (9) are one mechanism. They are merged under the shortest label. Three agents raised it independently, so it is promoted at 75 by multi-agent convergence, with a verified fix.
- `modules/cdp.vy._redeem` redemption-oracle-lag-extraction (3) and redemption-fee-below-oracle-deviation (9) are merged. It stays a LEAD because the attack pays only when the feed deviation is above the 0.5% fee, and no deployed feed is shown to have that deviation.
- `src/ministable.vy.__init__` stable-decimals-scale-mismatch (10) and unchecked-stablecoin-decimals (4, 9) are merged. It stays a LEAD: only the factory owner sets the value (Gate 3), and no unprivileged amplifier exists, so convergence does not promote it.
- `src/ministable.vy.__init__` owner-controlled-mock-oracle (agent 2): REJECTED. It needs the deployer to misuse a testnet-only mock (admin-action rule), and the testnet holds no value. The earlier lead about a mock that any caller can set is closed, because the mock setters now check the owner.
- `modules/erc20.vy.__module__` orphaned-owner-role (agent 2): REJECTED. No code path reads `owner`, so the issue is a stale comment with no material harm.
- `modules/cdp.vy._liquidate` unliquidatable-bad-debt (agent 3, LEAD): REJECTED. The else branch at cdp.vy:883-890 liquidates underwater positions and writes off the rest, so the earlier finding is refuted for this engine.

<!--F key=modules-cdp-vy|-liquidate|coarse-collateral-zero-seize conf=80 kind=FINDING agents=9,10-->

[80] **Liquidators receive zero collateral for coarse high-price collateral**

`modules/cdp.vy._liquidate` · Confidence: 80

**Description**
A liquidator burns mUSD and gets zero units of a 0-decimal high-price collateral, so no liquidator acts until the position is below 110%.

**Proof**
Seam: few-decimal collateral × `seized` floor to whole base units × the repay cap at the 150% target.

`cdp.__init__` accepts any `collateral_decimals <= 18`, including 0 (cdp.vy:767). The repo tests a supported `"no-decimals": (0, 8, 2_000)` market for `cdp_erc20` (tests/unitary/cdp_erc20/test_decimals.py).

1. PRICE_SCALE = 10**(36-8-0) = 1e28. At $2000, p = 2000e8 * 1e28 = 2e39.
2. The borrower deposits c = 1 and mints d = 1333e18. The ratio is 2e21*1e18 // 1333e18 = 1.5004e18, so the mint passes.
3. The price falls to $1900, so p = 1.9e39. The ratio is 1.425e18 < 1.5e18, so the position is liquidatable.
4. value = 1.9e39 >= 1.1e18 * 1333e18 = 1.4663e39, so the code takes the if branch (cdp.vy:869).
5. needed = 1.5e18*(1333e18+2) - 1.9e39 + 1e18 ≈ 9.95e37, so repay = ceil(needed / 4e17) ≈ 248.75e18 (cdp.vy:879).
6. seized = min(248.75e18 * 1.1e18 // 1.9e39, 1) = 0 (cdp.vy:881).

The liquidator burns about 248.75 mUSD and gets nothing. `max_repay` can only lower `repay`, because it sits inside `min(...)`. Seizing one unit needs repay >= 1727e18, which is above d. In general, the if branch gives `seized = 0` while the shortfall to 150% is below about 0.36 of one unit's value. No rational liquidator acts until value < 1.1·d, which is the else branch. If the price gaps through that level, the gap becomes `bad_debt` (at $1300: written_off = 1333 - 1181.8 ≈ 151 mUSD). At larger shortfalls, the floor still removes up to one whole unit from the liquidator's 10% bonus.

The `cdp_erc20` liquidation route is `cdp_erc20.liquidate` → `cdp._liquidate` → `_push(msg.sender, seized)`. `cdp_native` is not affected, because its collateral has 18 decimals.

**Fix**

```diff
     assert collateral_decimals <= 18 # dev: [cdp] unsupported collateral decimals
+    # @dev Coarse units floor `seized` to zero in `_liquidate`.
+    assert collateral_decimals >= 6 # dev: [cdp] unsupported collateral decimals
```

The fix is in `modules/cdp.vy` `__init__`. With 6 decimals, one unit of a $100,000 asset is worth $0.10, so the floor loss is dust. `cdp_native` passes 18 and is not changed. The 0-decimal test market must be removed or must expect a deploy revert.

<!--/F-->

<!--F key=modules-cdp-vy|-buy-surplus|zero-fee-oracle-swap conf=75 kind=FINDING agents=3,4,9-->

[75] **Buyers take the oracle lag from the surplus and the reserve**

`modules/cdp.vy._buy_surplus` · Confidence: 75

**Description**
A buyer pays collateral at an old oracle price with no fee and gets surplus mUSD, so the buyer keeps the price lag that the protocol loses.

**Proof**
`_buy_surplus` sets `bought: uint256 = paid * self._price() // PRECISION` (cdp.vy:944) with no spread. `_cover_bad_debt` sets `paid: uint256 = amount * PRECISION // self._price()` (cdp.vy:927) and also charges no fee. Chainlink feeds update only after a deviation threshold or a heartbeat, and `_price` accepts any answer younger than `ORACLE_TIMEOUT` (4500 s on mainnet). So the oracle price can lag the market by up to the threshold (0.5% for mainnet ETH/USD, 1–2% for many other feeds).

Trace on the native host: the market falls 0.5% to $1990 and the oracle still reports $2000. The attacker calls `buy_surplus()` with 50 ETH, which is worth $99,500 on the market. `bought = 50e18 * 2000e18 // 1e18 = 100,000e18` mUSD comes from the surplus. The reserve keeps ETH worth $99,500 for $100,000 of mUSD, a loss of $500 to the protocol. The attacker repeats this each time the feed lags. In the other direction, when the market rises above the oracle price, `cover_bad_debt` pays reserve collateral at the old, lower price.

Unprivileged route: `cdp_native.buy_surplus` / `cdp_erc20.buy_surplus` → `cdp._buy_surplus`; `cdp_native.cover_bad_debt` / `cdp_erc20.cover_bad_debt` → `cdp._cover_bad_debt`. The loss per trade is limited by the feed's deviation threshold. Three specialties raised this issue independently, so it is promoted at 75.

**Fix**

```diff
-    bought: uint256 = paid * self._price() // PRECISION
+    bought: uint256 = paid * self._price() // PRECISION * (PRECISION - REDEMPTION_FEE) // PRECISION
```

```diff
-    paid: uint256 = amount * PRECISION // self._price()
+    paid: uint256 = amount * (PRECISION - REDEMPTION_FEE) // self._price()
```

Both changes only lower the amount the protocol pays out, so they create no new revert or invariant break. `assert bought > 0` and `assert paid <= self.reserve` still hold. The spread reuses the 0.5% `REDEMPTION_FEE`. A larger, separate constant is better for feeds with a wider deviation threshold.

<!--/F-->

<!--F key=modules-cdp-vy|-liquidate|solvent-position-bad-debt kind=LEAD agents=3-->

- **Liquidation books bad debt on positions that still cover their debt** — `modules/cdp.vy._liquidate` — Code smells: the else branch runs when value < 1.1·d, so for value in [d, 1.1·d) the liquidator pays value/1.1 and `bad_debt` grows although the collateral covers d — Unverified: whether this Aave-style bonus rule is intended. Repaying d instead makes the bonus jump at 100%, which gives liquidators a reason to wait.

<!--/F-->

<!--F key=modules-cdp-vy|-liquidate|all-or-nothing-liquidation kind=LEAD agents=10-->

- **Underwater liquidation needs the full repay in one balance** — `modules/cdp.vy._liquidate` — Code smells: the else branch sets `repay = value // LIQUIDATION_PENALTY` and asserts `max_repay >= repay`, so no partial path exists — Unverified: whether liquidators can hold enough mUSD to close large underwater positions.

<!--/F-->

<!--F key=modules-cdp-vy|-redeem|redemption-oracle-lag-extraction kind=LEAD agents=3,9-->

- **Redeemers take borrower collateral when the oracle lag exceeds the fee** — `modules/cdp.vy._redeem` — Code smells: `paid = amount * (PRECISION - REDEMPTION_FEE) // self._price()` with a fixed 0.5% fee, and the redeemer picks the position and the time — Unverified: that a deployed feed has a deviation threshold above 0.5%.

<!--/F-->

<!--F key=src-ministable-vy|-init-|unchecked-stablecoin-decimals kind=LEAD agents=4,9,10-->

- **The constructor accepts mUSD decimals other than 18** — `src/ministable.vy.__init__` — Code smells: `decimals_` goes from `factory.deploy_ministable` to `erc20.__init__` with no check, but `cdp` treats 1e18 base units as $1 — Unverified: that the factory owner ever deploys with `decimals_ != 18`. The deploy script uses 18.

<!--/F-->

<!--F key=modules-cdp-vy|-price|chainlink-min-answer-clamp kind=LEAD agents=4-->

- **The price read accepts answers at the aggregator floor** — `modules/cdp.vy._price` — Code smells: `assert answer > 0` and the age check are the only validation — Unverified: whether the deployed aggregators still have active minAnswer/maxAnswer bounds.

<!--/F-->

<!--F key=modules-cdp-vy|-price|immutable-oracle-no-fallback kind=LEAD agents=4-->

- **A retired feed makes every price-based function fail forever** — `modules/cdp.vy._price` — Code smells: `ORACLE` and `SEQUENCER_UPTIME_FEED` are immutable and have no fallback — Unverified: whether a deployed feed is ever deprecated or paused.

<!--/F-->

<!--F key=modules-cdp-vy|mint|no-minimum-debt kind=LEAD agents=4-->

- **Borrowers can open positions too small to liquidate at a profit** — `modules/cdp.vy.mint` — Code smells: `mint` has no lower bound on the resulting debt — Unverified: the gas cost against the 10% bonus on the target chains.

<!--/F-->

<!--F key=modules-cdp-vy|-withdraw|oracle-dependent-withdraw-lock kind=LEAD agents=4-->

- **An oracle outage locks surplus collateral for every borrower with debt** — `modules/cdp.vy._withdraw` — Code smells: `_withdraw` calls `_collat_ratio`, which calls `_price()` when debt is more than zero — Unverified: the outage frequency and length of the deployed feeds and sequencer.

<!--/F-->
