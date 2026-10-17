import boa
import pytest

from src import ministable
from tests.mocks import mock_aggregator

ETH_USD_PRICE = 2000 * 10**8


@pytest.fixture
def oracle():
    return mock_aggregator.deploy(ETH_USD_PRICE)


@pytest.fixture
def stable(oracle):
    return ministable.deploy(oracle.address)


@pytest.fixture
def user():
    account = boa.env.generate_address("user")
    boa.env.set_balance(account, 100 * 10**18)
    return account


@pytest.fixture
def liquidator():
    account = boa.env.generate_address("liquidator")
    boa.env.set_balance(account, 100 * 10**18)
    return account
