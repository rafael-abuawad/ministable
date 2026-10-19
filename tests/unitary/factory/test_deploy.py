import boa
import pytest

from src import factory, ministable
from tests.utils.constants import ETH, ORACLE_TIMEOUT, ZERO_ADDRESS
from tests.utils.helpers import deploy_stable, filter_logs


@pytest.fixture(scope="module")
def blueprint():
    return ministable.deploy_as_blueprint()


@pytest.fixture
def stable_factory(blueprint, admin):
    with boa.env.prank(admin):
        return factory.deploy(blueprint.address)


def _deploy(stable_factory, oracle, sender):
    return stable_factory.deploy_ministable(
        "ministable",
        "mUSD",
        18,
        "ministable",
        "1",
        oracle.address,
        ORACLE_TIMEOUT,
        ZERO_ADDRESS,
        0,
        sender=sender,
    )


def test_deployer_is_owner(stable_factory, admin):
    assert stable_factory.owner() == admin
    assert stable_factory.pending_owner() == ZERO_ADDRESS


def test_blueprint_is_stored(stable_factory, blueprint):
    assert stable_factory.MINISTABLE_BLUEPRINT() == blueprint.address


def test_owner_deploys_ministable(stable_factory, oracle, admin):
    stable_address = _deploy(stable_factory, oracle, admin)
    logs = filter_logs(stable_factory, "MinistableDeployed")
    stable = ministable.at(stable_address)

    assert stable_factory.n_ministables() == 1
    assert stable_factory.ministables(0) == stable_address
    assert stable_factory.is_ministable(stable_address)
    assert stable.owner() == stable_factory.address
    assert stable.ORACLE() == oracle.address
    assert (stable.name(), stable.symbol(), stable.decimals()) == ("ministable", "mUSD", 18)

    assert len(logs) == 1
    assert logs[0].stable == stable_address
    assert logs[0].owner == admin


def test_deployed_ministable_accepts_collateral(stable_factory, oracle, admin, borrower):
    """Money Flow: borrower ETH → deployed ministable."""
    stable = ministable.at(_deploy(stable_factory, oracle, admin))

    stable.deposit(value=ETH, sender=borrower)

    assert stable.collateral(borrower) == ETH
    assert boa.env.get_balance(stable.address) == ETH


def test_stranger_cannot_deploy(stable_factory, oracle, borrower):
    with boa.reverts("ownable: caller is not the owner"):
        _deploy(stable_factory, oracle, borrower)


def test_ownership_transfers_in_two_steps(stable_factory, oracle, admin, borrower):
    successor = boa.env.generate_address("successor")

    stable_factory.transfer_ownership(successor, sender=admin)
    assert stable_factory.owner() == admin
    assert stable_factory.pending_owner() == successor

    with boa.reverts("ownable_2step: caller is not the new owner"):
        stable_factory.accept_ownership(sender=admin)
    with boa.reverts("ownable: caller is not the owner"):
        _deploy(stable_factory, oracle, successor)

    stable_factory.accept_ownership(sender=successor)

    assert stable_factory.owner() == successor
    assert stable_factory.pending_owner() == ZERO_ADDRESS
    assert stable_factory.is_ministable(_deploy(stable_factory, oracle, successor))
    with boa.reverts("ownable: caller is not the owner"):
        _deploy(stable_factory, oracle, admin)


def test_renounced_factory_cannot_deploy(stable_factory, oracle, admin):
    stable_factory.renounce_ownership(sender=admin)

    assert stable_factory.owner() == ZERO_ADDRESS
    with boa.reverts("ownable: caller is not the owner"):
        _deploy(stable_factory, oracle, admin)


def test_rejects_empty_blueprint(admin):
    with boa.reverts(dev="[factory] blueprint is not a contract"):
        factory.deploy(ZERO_ADDRESS, sender=admin)


def test_rejects_contract_without_blueprint_preamble(oracle, admin):
    implementation = deploy_stable(oracle.address)
    with boa.reverts(dev="[factory] not an erc-5202 blueprint"):
        factory.deploy(implementation.address, sender=admin)
