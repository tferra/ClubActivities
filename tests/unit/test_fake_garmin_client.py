import json

import pytest

from garmin_hub.garmin.client import (
    GarminIdentity,
    GarminUnavailable,
    InvalidCredentials,
    InvalidMfaCode,
    LoginSucceeded,
    MfaPending,
    RateLimited,
    TemporarilyBlocked,
    TokenRejected,
    VerifyResult,
)
from garmin_hub.garmin.fake import FAKE_MFA_CODE, FAKE_PASSWORD, FakeGarminClient


@pytest.fixture
def fake() -> FakeGarminClient:
    return FakeGarminClient()


def test_ok_login_returns_identity_and_tokens(fake) -> None:
    result = fake.start_login("ok+7@example.test", FAKE_PASSWORD)
    assert isinstance(result, LoginSucceeded)
    assert result.identity.profile_id == 7
    assert json.loads(result.tokens.value) == {"fake": 7, "rev": 1}
    again = fake.start_login("ok+7@example.test", FAKE_PASSWORD)
    assert json.loads(again.tokens.value)["rev"] == 2


def test_mfa_flow(fake) -> None:
    pending = fake.start_login("mfa+3@example.test", FAKE_PASSWORD)
    assert isinstance(pending, MfaPending)
    with pytest.raises(InvalidMfaCode):
        fake.complete_mfa(pending, "000000")
    result = fake.complete_mfa(pending, FAKE_MFA_CODE)  # sigue siendo reutilizable
    assert result.identity == GarminIdentity(3)


@pytest.mark.parametrize(
    ("email", "error"),
    [
        ("ratelimit@example.test", RateLimited),
        ("blocked@example.test", TemporarilyBlocked),
        ("down@example.test", GarminUnavailable),
        ("otra@example.test", InvalidCredentials),
        ("ok+x@example.test", InvalidCredentials),
    ],
)
def test_special_emails(fake, email, error) -> None:
    with pytest.raises(error):
        fake.start_login(email, FAKE_PASSWORD)


def test_wrong_password(fake) -> None:
    with pytest.raises(InvalidCredentials):
        fake.start_login("ok+1@example.test", "mala")
    with pytest.raises(InvalidCredentials):
        fake.start_login("mfa+1@example.test", "mala")


def test_discarded_pending_is_unusable(fake) -> None:
    pending = fake.start_login("mfa+3@example.test", FAKE_PASSWORD)
    fake.discard(pending)
    fake.discard(pending)  # idempotente
    with pytest.raises(GarminUnavailable):
        fake.complete_mfa(pending, FAKE_MFA_CODE)


def test_verify_default_and_high_ids(fake) -> None:
    tokens = fake.start_login("ok+5@example.test", FAKE_PASSWORD).tokens
    assert fake.verify(tokens) == VerifyResult(identity=GarminIdentity(5), renewed_tokens=None)
    high = fake.start_login("ok+9001@example.test", FAKE_PASSWORD).tokens
    with pytest.raises(TokenRejected):
        fake.verify(high)
    edge = fake.start_login("ok+9000@example.test", FAKE_PASSWORD).tokens
    with pytest.raises(TokenRejected):
        fake.verify(edge)


def test_script_verify_outcomes(fake) -> None:
    tokens = fake.start_login("ok+5@example.test", FAKE_PASSWORD).tokens
    fake.script_verify(5, RateLimited)
    with pytest.raises(RateLimited):
        fake.verify(tokens)
    fake.script_verify(5, "renew")
    result = fake.verify(tokens)
    assert result.renewed_tokens is not None
    assert json.loads(result.renewed_tokens.value)["fake"] == 5
    fake.script_verify(5, 6)  # identidad distinta
    assert fake.verify(tokens).identity == GarminIdentity(6)
    fake.script_verify(5, "ok")
    assert fake.verify(tokens).renewed_tokens is None


def test_calls_record_operation_and_email_only(fake) -> None:
    pending = fake.start_login("mfa+3@example.test", FAKE_PASSWORD)
    fake.complete_mfa(pending, FAKE_MFA_CODE)
    fake.discard(pending)
    assert fake.calls == [
        ("start_login", "mfa+3@example.test"),
        ("complete_mfa",),
        ("discard",),
    ]
    assert FAKE_PASSWORD not in str(fake.calls)
    assert FAKE_MFA_CODE not in str(fake.calls)


def test_hook_runs_before_returning(fake) -> None:
    seen = []
    fake.hooks["start_login"] = lambda: seen.append("hook")
    fake.start_login("ok+1@example.test", FAKE_PASSWORD)
    fake.start_login("ok+1@example.test", FAKE_PASSWORD)
    assert seen == ["hook"]  # se ejecuta una sola vez


def test_token_extra_is_embedded(fake) -> None:
    fake.token_extra = "CENTINELA"
    tokens = fake.start_login("ok+1@example.test", FAKE_PASSWORD).tokens
    assert b"CENTINELA" in tokens.value
