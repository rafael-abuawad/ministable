import boa
import pytest

from tests.mocks.deployers import MOCK_AGGREGATOR, MOCK_RECEIVER
from tests.utils.constants import (
    ETH,
    ETH_USD_PRICE,
    ORACLE_DECIMALS,
    POSITION_COLLATERAL,
    POSITION_DEBT,
)
from tests.utils.helpers import deploy_stable

boa.env.enable_fast_mode()

ACCOUNT_BALANCE = 100 * ETH


def _funded_account(name: str) -> str:
    account = boa.env.generate_address(name)
    boa.env.set_balance(account, ACCOUNT_BALANCE)
    return account


# ================= Accounts =================


@pytest.fixture(scope="module")
def admin():
    return boa.env.eoa


@pytest.fixture(scope="module")
def borrower():
    return _funded_account("borrower")


@pytest.fixture(scope="module")
def liquidator():
    return _funded_account("liquidator")


@pytest.fixture(scope="module")
def recipient():
    return _funded_account("recipient")


# ================= Contracts =================


@pytest.fixture(scope="module")
def oracle():
    return MOCK_AGGREGATOR.deploy(ETH_USD_PRICE, ORACLE_DECIMALS)


@pytest.fixture(scope="module")
def stable(oracle, admin):
    with boa.env.prank(admin):
        return deploy_stable(oracle.address)


@pytest.fixture(scope="module")
def receiver(stable):
    contract = MOCK_RECEIVER.deploy(stable.address)
    boa.env.set_balance(contract.address, ACCOUNT_BALANCE)
    return contract


# ================= Positions =================
# Function-scoped: module-scoped state would leak into every later test
# in the module that shares the same accounts.


@pytest.fixture
def borrower_position(stable, borrower):
    """1 ETH collateral, 1000 mUSD debt -> 200% at $2000."""
    stable.deposit(value=POSITION_COLLATERAL, sender=borrower)
    stable.mint(POSITION_DEBT, sender=borrower)
    return borrower


@pytest.fixture
def funded_liquidator(stable, liquidator):
    """Liquidator holding enough mUSD to repay the borrower's debt."""
    stable.deposit(value=10 * ETH, sender=liquidator)
    stable.mint(POSITION_DEBT, sender=liquidator)
    return liquidator
