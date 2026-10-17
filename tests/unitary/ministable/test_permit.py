import boa
import pytest
from eth_abi import encode
from eth_account import Account
from eth_utils import keccak

from tests.utils.constants import ETH

PERMIT_TYPES = {
    "Permit": [
        {"name": "owner", "type": "address"},
        {"name": "spender", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "nonce", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
    ]
}


@pytest.fixture(scope="module")
def signer():
    return Account.create()


def _sign_permit(stable, signer, spender, value, deadline, nonce=None):
    _, name, version, chain_id, verifying_contract, _, _ = stable.eip712Domain()
    domain = {
        "name": name,
        "version": version,
        "chainId": chain_id,
        "verifyingContract": verifying_contract,
    }
    message = {
        "owner": signer.address,
        "spender": spender,
        "value": value,
        "nonce": stable.nonces(signer.address) if nonce is None else nonce,
        "deadline": deadline,
    }
    signed = Account.sign_typed_data(signer.key, domain, PERMIT_TYPES, message)
    return signed.v, signed.r.to_bytes(32, "big"), signed.s.to_bytes(32, "big")


EIP712_DOMAIN_TYPE_HASH = keccak(
    text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)


def _deadline():
    return boa.env.evm.patch.timestamp + 3600


def test_permit_sets_allowance(stable, signer, recipient):
    deadline = _deadline()
    v, r, s = _sign_permit(stable, signer, recipient, 100 * ETH, deadline)

    stable.permit(signer.address, recipient, 100 * ETH, deadline, v, r, s, sender=recipient)

    assert stable.allowance(signer.address, recipient) == 100 * ETH
    assert stable.nonces(signer.address) == 1


def test_permit_replay_reverts(stable, signer, recipient):
    deadline = _deadline()
    v, r, s = _sign_permit(stable, signer, recipient, 100 * ETH, deadline)
    stable.permit(signer.address, recipient, 100 * ETH, deadline, v, r, s)

    with boa.reverts(dev="[erc20] invalid signature"):
        stable.permit(signer.address, recipient, 100 * ETH, deadline, v, r, s)


def test_permit_wrong_value_reverts(stable, signer, recipient):
    deadline = _deadline()
    v, r, s = _sign_permit(stable, signer, recipient, 100 * ETH, deadline)

    with boa.reverts(dev="[erc20] invalid signature"):
        stable.permit(signer.address, recipient, 101 * ETH, deadline, v, r, s)


def test_permit_expired_deadline_reverts(stable, signer, recipient):
    deadline = _deadline()
    v, r, s = _sign_permit(stable, signer, recipient, 100 * ETH, deadline)
    boa.env.time_travel(seconds=3601)

    with boa.reverts(dev="[erc20] expired deadline"):
        stable.permit(signer.address, recipient, 100 * ETH, deadline, v, r, s)


def test_domain_separator(stable):
    """Matches the EIP-712 hash built off-chain from `eip712Domain()`."""
    _, name, version, chain_id, verifying_contract, _, _ = stable.eip712Domain()
    expected = keccak(
        encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [EIP712_DOMAIN_TYPE_HASH, keccak(text=name), keccak(text=version), chain_id, verifying_contract],
        )
    )

    assert stable.DOMAIN_SEPARATOR() == expected
