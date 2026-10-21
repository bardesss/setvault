from __future__ import annotations

from itsdangerous import TimestampSigner
from setvault_core.services.sessions import SessionData, SessionSigner

SECRET = "test-secret-key"


def _raw_sign(payload: str) -> str:
    return TimestampSigner(SECRET, salt="setvault.session").sign(payload).decode("ascii")


def test_roundtrip_carries_version():
    signer = SessionSigner(SECRET)
    assert signer.read(signer.issue("u", 3)) == SessionData("u", 3)


def test_legacy_two_part_payload_is_version_zero():
    signer = SessionSigner(SECRET)
    assert signer.read(_raw_sign("u:nonce")) == SessionData("u", 0)


def test_malformed_payloads_return_none():
    signer = SessionSigner(SECRET)
    for payload in ("u:abc:n", "u:1:n:extra", ":1:n"):
        assert signer.read(_raw_sign(payload)) is None, payload


def test_bad_signature_returns_none():
    assert SessionSigner(SECRET).read("garbage") is None
