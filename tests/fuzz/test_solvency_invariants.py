"""Stateful fuzzing: a reference model shadows ministable through random
deposits, mints, burns, withdrawals, transfers, price moves and liquidations."""

import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from src import ministable
from tests.mocks.deployers import MOCK_AGGREGATOR
from tests.utils.constants import ETH, ETH_USD_PRICE, MIN_COLLAT_RATIO, PRECISION
from tests.utils.helpers import max_mintable

N_ACTORS = 4
STARTING_ETH = 1_000 * ETH

# A keeper holding a large mUSD buffer, so liquidations can actually succeed
# instead of reverting for lack of mUSD.
KEEPER_ETH = 1_000_000 * ETH
KEEPER_DEBT = 100_000_000 * ETH  # 200% at $2000 with all of KEEPER_ETH locked

actor_st = st.integers(min_value=0, max_value=N_ACTORS - 1)
eth_amount_st = st.integers(min_value=1, max_value=50 * ETH)
musd_amount_st = st.integers(min_value=1, max_value=200_000 * ETH)
feed_price_st = st.integers(min_value=100 * 10**8, max_value=10_000 * 10**8)


class SolvencyMachine(RuleBasedStateMachine):
    @initialize()
    def setup(self):
        self.oracle = MOCK_AGGREGATOR.deploy(ETH_USD_PRICE)
        self.stable = ministable.deploy("ministable", "mUSD", 18, self.oracle.address)
        self.feed_price = ETH_USD_PRICE
        self.actors = [boa.env.generate_address(f"actor{i}") for i in range(N_ACTORS)]
        for actor in self.actors:
            boa.env.set_balance(actor, STARTING_ETH)
        self.collateral = {a: 0 for a in self.actors}
        self.debt = {a: 0 for a in self.actors}
        self.balance = {a: 0 for a in self.actors}

        self.keeper = boa.env.generate_address("keeper")
        boa.env.set_balance(self.keeper, KEEPER_ETH)
        self.stable.deposit(value=KEEPER_ETH, sender=self.keeper)
        self.stable.mint(KEEPER_DEBT, sender=self.keeper)
        self.collateral[self.keeper] = KEEPER_ETH
        self.debt[self.keeper] = KEEPER_DEBT
        self.balance[self.keeper] = KEEPER_DEBT
        self.liquidations = 0

    # ================= Model helpers =================

    def _ratio(self, collateral: int, debt: int) -> int:
        if debt == 0:
            return 2**256 - 1
        value = collateral * self.feed_price * 10**10 // PRECISION
        return value * PRECISION // debt

    def _underwater(self) -> list:
        return [a for a in self.actors if self._ratio(self.collateral[a], self.debt[a]) < MIN_COLLAT_RATIO]

    # ================= Rules =================

    @rule(i=actor_st, amount=eth_amount_st)
    def deposit(self, i, amount):
        actor = self.actors[i]
        amount = min(amount, boa.env.get_balance(actor))
        if amount == 0:
            return
        self.stable.deposit(value=amount, sender=actor)
        self.collateral[actor] += amount

    @rule(i=actor_st, amount=musd_amount_st)
    def mint(self, i, amount):
        actor = self.actors[i]
        healthy = self._ratio(self.collateral[actor], self.debt[actor] + amount) >= MIN_COLLAT_RATIO
        if healthy:
            self.stable.mint(amount, sender=actor)
            self.debt[actor] += amount
            self.balance[actor] += amount
        else:
            with boa.reverts("ministable: undercollateralized"):
                self.stable.mint(amount, sender=actor)

    @rule(i=actor_st, amount=eth_amount_st)
    def open_max_position(self, i, amount):
        """Deposit and mint to the limit in one step: any price drop makes it liquidatable."""
        self.deposit(i, amount)
        self.mint_max(i)

    @rule(i=actor_st)
    def mint_max(self, i):
        actor = self.actors[i]
        amount = max_mintable(self.collateral[actor], self.feed_price) - self.debt[actor]
        if amount > 0:
            self.stable.mint(amount, sender=actor)
            self.debt[actor] += amount
            self.balance[actor] += amount

    @rule(i=actor_st, amount=musd_amount_st)
    def burn(self, i, amount):
        actor = self.actors[i]
        if amount <= self.debt[actor] and amount <= self.balance[actor]:
            self.stable.burn(amount, sender=actor)
            self.debt[actor] -= amount
            self.balance[actor] -= amount
        else:
            with boa.reverts():
                self.stable.burn(amount, sender=actor)

    @rule(i=actor_st, amount=eth_amount_st)
    def withdraw(self, i, amount):
        actor = self.actors[i]
        ok = amount <= self.collateral[actor] and (
            self._ratio(self.collateral[actor] - amount, self.debt[actor]) >= MIN_COLLAT_RATIO
        )
        if ok:
            self.stable.withdraw(amount, sender=actor)
            self.collateral[actor] -= amount
        else:
            with boa.reverts():
                self.stable.withdraw(amount, sender=actor)

    @rule(i=actor_st, j=actor_st, amount=musd_amount_st)
    def transfer(self, i, j, amount):
        sender, to = self.actors[i], self.actors[j]
        amount = min(amount, self.balance[sender])
        self.stable.transfer(to, amount, sender=sender)
        self.balance[sender] -= amount
        self.balance[to] += amount

    @rule(feed_price=feed_price_st)
    def set_price(self, feed_price):
        self._set_price(feed_price)

    @rule(drop_bps=st.integers(min_value=1, max_value=5_000))
    def crash_price(self, drop_bps):
        """Drop the price by up to 50%, pushing maxed-out positions underwater."""
        self._set_price(max(self.feed_price * (10_000 - drop_bps) // 10_000, 1))

    def _set_price(self, feed_price):
        self.oracle.set_answer(feed_price)
        self.feed_price = feed_price

    @rule(i=actor_st, j=actor_st)
    def liquidate(self, i, j):
        liquidator, user = self.actors[i], self.actors[j]
        unhealthy = self._ratio(self.collateral[user], self.debt[user]) < MIN_COLLAT_RATIO
        if unhealthy and self.balance[liquidator] >= self.debt[user]:
            self._liquidate(liquidator, user)
        else:
            with boa.reverts():
                self.stable.liquidate(user, sender=liquidator)

    @precondition(lambda self: self._underwater())
    @rule(data=st.data())
    def keeper_liquidate(self, data):
        user = data.draw(st.sampled_from(self._underwater()))
        self._liquidate(self.keeper, user)

    @rule(j=actor_st)
    def keeper_liquidate_healthy(self, j):
        user = self.actors[j]
        if self._ratio(self.collateral[user], self.debt[user]) >= MIN_COLLAT_RATIO:
            with boa.reverts("ministable: position healthy"):
                self.stable.liquidate(user, sender=self.keeper)

    def _liquidate(self, liquidator, user):
        liquidator_eth = boa.env.get_balance(liquidator)
        self.stable.liquidate(user, sender=liquidator)
        assert boa.env.get_balance(liquidator) == liquidator_eth + self.collateral[user]
        self.balance[liquidator] -= self.debt[user]
        self.debt[user] = 0
        self.collateral[user] = 0
        self.liquidations += 1

    # ================= Invariants =================

    @invariant()
    def model_matches_contract(self):
        for actor in self.collateral:
            assert self.stable.collateral(actor) == self.collateral[actor]
            assert self.stable.debt(actor) == self.debt[actor]
            assert self.stable.balanceOf(actor) == self.balance[actor]

    @invariant()
    def supply_equals_total_debt(self):
        assert self.stable.totalSupply() == sum(self.debt.values())

    @invariant()
    def eth_held_equals_total_collateral(self):
        assert boa.env.get_balance(self.stable.address) == sum(self.collateral.values())

    @invariant()
    def no_eth_created_or_destroyed(self):
        held = sum(boa.env.get_balance(a) for a in self.collateral)
        assert held + boa.env.get_balance(self.stable.address) == N_ACTORS * STARTING_ETH + KEEPER_ETH


TestSolvency = SolvencyMachine.TestCase
TestSolvency.settings = settings(max_examples=100, stateful_step_count=40, deadline=None)
