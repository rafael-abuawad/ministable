"""Stateful fuzzing: a reference model shadows ministable through random
deposits, mints, burns, withdrawals, transfers, price moves, interest,
surplus purchases and liquidations."""

import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from tests.mocks.deployers import MOCK_AGGREGATOR
from tests.utils.constants import (
    ETH,
    ETH_USD_PRICE,
    MAX_STABILITY_FEE,
    MIN_COLLAT_RATIO,
    ORACLE_DECIMALS,
    PRECISION,
)
from tests.utils.helpers import deploy_stable, max_mintable

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


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


class SolvencyMachine(RuleBasedStateMachine):
    @initialize()
    def setup(self):
        self.oracle = MOCK_AGGREGATOR.deploy(ETH_USD_PRICE, ORACLE_DECIMALS)
        self.stable = deploy_stable(self.oracle.address, fee=MAX_STABILITY_FEE)
        self.feed_price = ETH_USD_PRICE
        self.actors = [boa.env.generate_address(f"actor{i}") for i in range(N_ACTORS)]
        for actor in self.actors:
            boa.env.set_balance(actor, STARTING_ETH)
        self.collateral = {a: 0 for a in self.actors}
        self.shares = {a: 0 for a in self.actors}
        self.balance = {a: 0 for a in self.actors}
        self.index = PRECISION
        self.last_accrual = boa.env.timestamp
        self.surplus = 0
        self.reserve = 0
        # Rounding lets debt run a few wei ahead of supply; count the steps.
        self.steps = 0

        self.keeper = boa.env.generate_address("keeper")
        boa.env.set_balance(self.keeper, KEEPER_ETH)
        self.stable.deposit(value=KEEPER_ETH, sender=self.keeper)
        self.stable.mint(KEEPER_DEBT, sender=self.keeper)
        self.collateral[self.keeper] = KEEPER_ETH
        self.shares[self.keeper] = KEEPER_DEBT
        self.balance[self.keeper] = KEEPER_DEBT
        self.liquidations = 0

    # ================= Model helpers =================

    def _index_now(self) -> int:
        elapsed = boa.env.timestamp - self.last_accrual
        return self.index + self.index * MAX_STABILITY_FEE * elapsed // PRECISION

    def _pending_fee(self) -> int:
        return sum(self.shares.values()) * (self._index_now() - self.index) // PRECISION

    def _surplus_now(self) -> int:
        return self.surplus + self._pending_fee()

    def _accrue(self):
        """Mirror `_accrue`. Call only once the contract call has succeeded:
        a revert rolls the contract's accrual back, and interest compounds per accrual."""
        index = self._index_now()
        if index == self.index:
            return
        self.surplus += self._pending_fee()
        self.index = index
        self.last_accrual = boa.env.timestamp

    def _debt_of(self, shares: int) -> int:
        return _ceil_div(shares * self._index_now(), PRECISION)

    def _debt(self, actor) -> int:
        return self._debt_of(self.shares[actor])

    def _ratio(self, collateral: int, debt: int) -> int:
        if debt == 0:
            return 2**256 - 1
        value = collateral * self.feed_price * 10**10 // PRECISION
        return value * PRECISION // debt

    def _underwater(self) -> list:
        return [
            a
            for a in self.actors
            if self._ratio(self.collateral[a], self._debt(a)) < MIN_COLLAT_RATIO
        ]

    def _try_mint(self, actor, amount) -> bool:
        """Mint if the model says the result stays healthy; check a revert otherwise."""
        new_shares = self.shares[actor] + _ceil_div(amount * PRECISION, self._index_now())
        healthy = (
            self._ratio(self.collateral[actor], self._debt_of(new_shares))
            >= MIN_COLLAT_RATIO
        )
        if healthy:
            self.stable.mint(amount, sender=actor)
            self._accrue()
            self.shares[actor] = new_shares
            self.balance[actor] += amount
        else:
            with boa.reverts(dev="[ministable] undercollateralized"):
                self.stable.mint(amount, sender=actor)
        return healthy

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
        self.steps += 1
        self._try_mint(self.actors[i], amount)

    @rule(i=actor_st, amount=eth_amount_st)
    def open_max_position(self, i, amount):
        """Deposit and mint to the limit in one step: any price drop makes it liquidatable."""
        self.deposit(i, amount)
        self.mint_max(i)

    @rule(i=actor_st)
    def mint_max(self, i):
        actor = self.actors[i]
        self.steps += 1
        amount = max_mintable(self.collateral[actor], self.feed_price) - self._debt(actor)
        # Share rounding can push the exact limit one wei over; step down.
        while amount > 0 and not self._try_mint(actor, amount):
            amount -= 1

    @rule(i=actor_st, amount=musd_amount_st)
    def burn(self, i, amount):
        actor = self.actors[i]
        self.steps += 1
        debt = self._debt(actor)
        if amount <= debt and amount <= self.balance[actor]:
            self.stable.burn(amount, sender=actor)
            self._accrue()
            removed = self.shares[actor] if amount == debt else amount * PRECISION // self.index
            self.shares[actor] -= removed
            self.balance[actor] -= amount
        else:
            with boa.reverts():
                self.stable.burn(amount, sender=actor)

    @rule(i=actor_st)
    def repay_all(self, i):
        """Close out the whole debt, buying any missing mUSD from the surplus."""
        actor = self.actors[i]
        self.steps += 1
        debt = self._debt(actor)
        missing = debt - self.balance[actor]
        if missing > 0:
            eth = _ceil_div(missing * PRECISION, self.feed_price * 10**10)
            if missing > self._surplus_now() or eth > boa.env.get_balance(actor):
                return
            self._buy_surplus(actor, eth)
        if debt > 0:
            self.stable.burn(debt, sender=actor)
            self._accrue()
            self.shares[actor] = 0
            self.balance[actor] -= debt

    @rule(i=actor_st, amount=eth_amount_st)
    def withdraw(self, i, amount):
        actor = self.actors[i]
        ok = amount <= self.collateral[actor] and (
            self._ratio(self.collateral[actor] - amount, self._debt(actor))
            >= MIN_COLLAT_RATIO
        )
        if ok:
            self.stable.withdraw(amount, sender=actor)
            self._accrue()
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

    @rule(i=actor_st, eth=st.integers(min_value=0, max_value=10 * ETH))
    def buy_surplus(self, i, eth):
        actor = self.actors[i]
        self.steps += 1
        eth = min(eth, boa.env.get_balance(actor))
        out = eth * self.feed_price * 10**10 // PRECISION
        if 0 < out <= self._surplus_now():
            self._buy_surplus(actor, eth)
        else:
            with boa.reverts():
                self.stable.buy_surplus(value=eth, sender=actor)

    def _buy_surplus(self, actor, eth):
        out = self.stable.buy_surplus(value=eth, sender=actor)
        self._accrue()
        assert out == eth * self.feed_price * 10**10 // PRECISION
        self.surplus -= out
        self.reserve += eth
        self.balance[actor] += out

    @rule(seconds=st.integers(min_value=1, max_value=30 * 86400))
    def warp(self, seconds):
        """Let interest build up, keeping the oracle fresh."""
        boa.env.time_travel(seconds=seconds)
        self._set_price(self.feed_price)

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
        debt = self._debt(user)
        unhealthy = self._ratio(self.collateral[user], debt) < MIN_COLLAT_RATIO
        if unhealthy and self.balance[liquidator] >= debt:
            self._liquidate(liquidator, user)
        else:
            with boa.reverts():
                self.stable.liquidate(user, sender=liquidator)

    @precondition(lambda self: self._underwater())
    @rule(data=st.data())
    def keeper_liquidate(self, data):
        user = data.draw(st.sampled_from(self._underwater()))
        if self.balance[self.keeper] >= self._debt(user):
            self._liquidate(self.keeper, user)

    @rule(j=actor_st)
    def keeper_liquidate_healthy(self, j):
        user = self.actors[j]
        if self._ratio(self.collateral[user], self._debt(user)) >= MIN_COLLAT_RATIO:
            with boa.reverts(dev="[ministable] position healthy"):
                self.stable.liquidate(user, sender=self.keeper)

    def _liquidate(self, liquidator, user):
        self.steps += 1
        debt = self._debt(user)
        liquidator_eth = boa.env.get_balance(liquidator)
        self.stable.liquidate(user, sender=liquidator)
        self._accrue()
        assert boa.env.get_balance(liquidator) == liquidator_eth + self.collateral[user]
        self.balance[liquidator] -= debt
        self.shares[user] = 0
        self.collateral[user] = 0
        self.liquidations += 1

    # ================= Invariants =================

    @invariant()
    def model_matches_contract(self):
        assert self.stable.rate_index() == self.index
        assert self.stable.surplus() == self.surplus
        assert self.stable.reserve() == self.reserve
        for actor in self.collateral:
            assert self.stable.collateral(actor) == self.collateral[actor]
            assert self.stable.debt_shares(actor) == self.shares[actor]
            assert self.stable.debt(actor) == self._debt(actor)
            assert self.stable.balanceOf(actor) == self.balance[actor]

    @invariant()
    def supply_backed_by_debt(self):
        """Every mUSD is owed back by a borrower; rounding only ever favours the protocol.
        Debt views include interest not yet minted to the surplus, so count it in."""
        supply = self.stable.totalSupply() + self._pending_fee()
        total_debt = sum(self.stable.debt(a) for a in self.collateral)
        assert supply <= total_debt <= supply + len(self.collateral) + 2 * self.steps
        assert self.stable.total_debt_shares() == sum(self.shares.values())

    @invariant()
    def eth_held_equals_collateral_plus_reserve(self):
        assert boa.env.get_balance(self.stable.address) == (
            sum(self.collateral.values()) + self.reserve
        )

    @invariant()
    def no_eth_created_or_destroyed(self):
        held = sum(boa.env.get_balance(a) for a in self.collateral)
        assert (
            held + boa.env.get_balance(self.stable.address)
            == N_ACTORS * STARTING_ETH + KEEPER_ETH
        )


TestSolvency = SolvencyMachine.TestCase
TestSolvency.settings = settings(
    max_examples=100, stateful_step_count=40, deadline=None
)
