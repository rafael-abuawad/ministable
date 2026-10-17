from tests.utils.constants import MIN_COLLAT_RATIO, ORACLE_TIMEOUT


def test_token_metadata(stable):
    assert stable.name() == "ministable"
    assert stable.symbol() == "mUSD"
    assert stable.decimals() == 18


def test_initial_supply_is_zero(stable):
    assert stable.totalSupply() == 0


def test_risk_parameters(stable):
    assert stable.MIN_COLLAT_RATIO() == MIN_COLLAT_RATIO
    assert stable.ORACLE_TIMEOUT() == ORACLE_TIMEOUT


def test_oracle_is_set(stable, oracle):
    assert stable.ORACLE() == oracle.address


def test_deployer_is_owner(stable, admin):
    assert stable.owner() == admin


def test_eip712_domain(stable):
    _, name, version, _, verifying_contract, _, _ = stable.eip712Domain()
    assert name == "ministable"
    assert version == "1"
    assert verifying_contract == stable.address
