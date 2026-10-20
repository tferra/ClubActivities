"""Mapeo de errores y recorrido de estrategias de `GarminConnectClient`, sin red."""

import json
import random
from types import SimpleNamespace

import pytest
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_hub.garmin import garminconnect_client as gcc
from garmin_hub.garmin.client import (
    GarminError,
    GarminProtocolError,
    GarminTokens,
    GarminUnavailable,
    InvalidCredentials,
    InvalidMfaCode,
    LoginSucceeded,
    MfaPending,
    RateLimited,
    TemporarilyBlocked,
    TokenRejected,
)

GOOD_DUMPS = {"di_token": "t", "di_refresh_token": "r", "di_client_id": "c"}
ORIGINAL_TEXT = "secret-library-detail ana@club.test"


def connection_error(status: int | None = None, text: str = ORIGINAL_TEXT) -> Exception:
    exc = GarminConnectConnectionError(text)
    if status is not None:
        exc.response = SimpleNamespace(status_code=status)
    return exc


class Lib:
    """Doble de `garminconnect.client.Client` con un guion por estrategia."""

    def __init__(self) -> None:
        self.script: dict[str, object] = {}
        self.profile: object = {"profileId": 42}
        self.dumps_data: dict = dict(GOOD_DUMPS)
        self.dumps_after: dict | None = None
        self.api_error: Exception | None = None
        self.resume_error: Exception | None = None
        self.logins: list[str] = []
        self.resumed: list[tuple] = []
        self.instances = 0
        self.cleared = 0

    def factory(self, *args, **kwargs):
        lib = self
        lib.instances += 1

        class Instance:
            def __init__(self) -> None:
                self.skip_strategies: set[str] = set()
                self._calls = 0

            def login(self, email, password, prompt_mfa=None, return_on_mfa=False):
                assert return_on_mfa is True
                active = [s for s in gcc.STRATEGIES if s not in self.skip_strategies]
                assert len(active) == 1
                name = active[0]
                lib.logins.append(name)
                outcome = lib.script.get(name, "ok")
                if isinstance(outcome, list):
                    outcome = outcome.pop(0) if outcome else "ok"
                if isinstance(outcome, Exception):
                    raise outcome
                if outcome == "mfa":
                    return "needs_mfa", None
                return None, None

            def resume_login(self, state, code):
                lib.resumed.append((state, code))
                if lib.resume_error:
                    raise lib.resume_error
                return None, None

            def connectapi(self, path):
                assert path == "/userprofile-service/socialProfile"
                self._calls += 1
                if lib.api_error:
                    raise lib.api_error
                return lib.profile

            def dumps(self):
                if self._calls and lib.dumps_after is not None:
                    return json.dumps(lib.dumps_after)
                return json.dumps(lib.dumps_data)

            def loads(self, data):
                json.loads(data)

            def _clear_auth_state(self, **kwargs):
                lib.cleared += 1

        return Instance()


class Clock:
    def __init__(self, step: float = 0.0) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


@pytest.fixture
def lib(monkeypatch) -> Lib:
    double = Lib()
    monkeypatch.setattr(gcc, "Client", double.factory)
    return double


@pytest.fixture
def sleeps() -> list[float]:
    return []


def make(sleeps, **kwargs) -> gcc.GarminConnectClient:
    options = {
        "max_retries": 2,
        "login_max_retries": 0,
        "strategy_pause": 2.0,
        "login_budget": 45.0,
        "sleep": sleeps.append,
        "clock": Clock(),
        "rng": random.Random(7),
    }
    options.update(kwargs)
    return gcc.GarminConnectClient(**options)


def test_strategy_order_matches_research() -> None:
    assert gcc.STRATEGIES == (
        "mobile+cffi",
        "mobile+requests",
        "widget+cffi",
        "portal+cffi",
        "portal+requests",
    )


def test_login_success_first_strategy(lib, sleeps) -> None:
    result = make(sleeps).start_login("a@b.test", "pw")
    assert isinstance(result, LoginSucceeded)
    assert result.identity.profile_id == 42
    assert json.loads(result.tokens.value) == GOOD_DUMPS
    assert lib.logins == ["mobile+cffi"]
    assert sleeps == []


def test_generic_failure_pauses_and_moves_on(lib, sleeps) -> None:
    lib.script = {
        "mobile+cffi": connection_error(text="All login strategies exhausted: boom"),
        "mobile+requests": connection_error(503),
    }
    result = make(sleeps).start_login("a@b.test", "pw")
    assert isinstance(result, LoginSucceeded)
    assert lib.logins == ["mobile+cffi", "mobile+requests", "widget+cffi"]
    assert len(sleeps) == 2
    assert all(1.0 <= s <= 3.0 for s in sleeps)


def test_all_strategies_fail_raises_unavailable(lib, sleeps) -> None:
    lib.script = {name: connection_error(text="boom") for name in gcc.STRATEGIES}
    with pytest.raises(GarminUnavailable):
        make(sleeps).start_login("a@b.test", "pw")
    assert lib.logins == list(gcc.STRATEGIES)
    assert len(sleeps) == 4


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            GarminConnectTooManyRequestsError("All login strategies rate limited (429)."),
            RateLimited,
        ),
        (connection_error(403), TemporarilyBlocked),
        (
            connection_error(text="Mobile login: HTTP 403 (Cloudflare bot challenge)"),
            TemporarilyBlocked,
        ),
        (GarminConnectAuthenticationError(ORIGINAL_TEXT), InvalidCredentials),
    ],
)
def test_stop_conditions_do_not_try_more_strategies(lib, sleeps, exc, expected) -> None:
    lib.script = {"mobile+cffi": exc}
    with pytest.raises(expected) as err:
        make(sleeps).start_login("a@b.test", "pw")
    assert lib.logins == ["mobile+cffi"]
    assert sleeps == []
    assert ORIGINAL_TEXT not in str(err.value)


def test_budget_exhausted_before_next_strategy(lib, sleeps) -> None:
    lib.script = {name: connection_error(text="boom") for name in gcc.STRATEGIES}
    with pytest.raises(GarminUnavailable):
        make(sleeps, clock=Clock(step=30.0)).start_login("a@b.test", "pw")
    assert lib.logins == ["mobile+cffi"]


def test_login_retries_disabled_by_default(lib, sleeps) -> None:
    lib.script = {"mobile+cffi": [GarminConnectTooManyRequestsError("429"), "ok"]}
    with pytest.raises(RateLimited):
        make(sleeps).start_login("a@b.test", "pw")
    assert lib.logins == ["mobile+cffi"]


def test_login_retry_once_after_backoff(lib, sleeps) -> None:
    lib.script = {"mobile+cffi": [GarminConnectTooManyRequestsError("429"), "ok"]}
    result = make(sleeps, login_max_retries=1).start_login("a@b.test", "pw")
    assert isinstance(result, LoginSucceeded)
    assert lib.logins == ["mobile+cffi", "mobile+cffi"]
    assert len(sleeps) == 1 and 0.5 <= sleeps[0] <= 1.5


def test_mfa_pending_and_resume(lib, sleeps) -> None:
    lib.script = {"mobile+cffi": "mfa"}
    client = make(sleeps)
    pending = client.start_login("a@b.test", "pw")
    assert isinstance(pending, MfaPending)
    lib.resume_error = GarminConnectAuthenticationError("bad code")
    with pytest.raises(InvalidMfaCode):
        client.complete_mfa(pending, "000000")
    lib.resume_error = None
    result = client.complete_mfa(pending, "123456")
    assert isinstance(result, LoginSucceeded)
    assert lib.resumed[-1] == (None, "123456")
    client.discard(pending)
    assert lib.cleared == 1


def test_discard_swallows_errors(sleeps) -> None:
    class Broken:
        def _clear_auth_state(self, **kwargs):
            raise RuntimeError("x")

    make(sleeps).discard(MfaPending(handle=Broken()))


def test_missing_refresh_token_is_protocol_error(lib, sleeps) -> None:
    lib.dumps_data = {"di_token": None, "di_refresh_token": None, "di_client_id": None}
    with pytest.raises(GarminProtocolError):
        make(sleeps).start_login("a@b.test", "pw")


@pytest.mark.parametrize("profile", [{}, {"profileId": "42"}, {"profileId": True}, [], None])
def test_missing_profile_id_is_protocol_error(lib, sleeps, profile) -> None:
    lib.profile = profile
    with pytest.raises(GarminProtocolError):
        make(sleeps).start_login("a@b.test", "pw")


TOKENS = GarminTokens(json.dumps(GOOD_DUMPS).encode())


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (connection_error(401), TokenRejected),
        (connection_error(403), TokenRejected),
        (connection_error(text="API Error 401 - Unauthorized"), TokenRejected),
        (connection_error(503), GarminUnavailable),
        (connection_error(text="API Error 502"), GarminUnavailable),
        (connection_error(), GarminUnavailable),
        (GarminConnectTooManyRequestsError("429"), RateLimited),
        (connection_error(text="API Error 429"), RateLimited),
        (GarminConnectAuthenticationError("refresh failed"), TokenRejected),
        (ConnectionResetError("reset"), GarminUnavailable),
        (ValueError("weird"), GarminProtocolError),
    ],
)
def test_verify_error_mapping(lib, sleeps, exc, expected) -> None:
    lib.api_error = exc
    with pytest.raises(expected) as err:
        make(sleeps, max_retries=0).verify(TOKENS)
    assert ORIGINAL_TEXT not in str(err.value)
    assert str(err.value) == expected.message


def test_verify_retries_transient_with_backoff(lib, sleeps) -> None:
    lib.api_error = connection_error(503)
    with pytest.raises(GarminUnavailable):
        make(sleeps, max_retries=2).verify(TOKENS)
    assert lib.instances == 3
    assert len(sleeps) == 2


def test_verify_no_retry_on_token_rejected(lib, sleeps) -> None:
    lib.api_error = connection_error(401)
    with pytest.raises(TokenRejected):
        make(sleeps, max_retries=2).verify(TOKENS)
    assert sleeps == []


def test_verify_detects_renewal(lib, sleeps) -> None:
    result = make(sleeps).verify(TOKENS)
    assert result.identity.profile_id == 42 and result.renewed_tokens is None
    lib.dumps_after = {**GOOD_DUMPS, "di_token": "t2"}
    result = make(sleeps).verify(TOKENS)
    assert json.loads(result.renewed_tokens.value)["di_token"] == "t2"


def test_every_error_has_fixed_english_message() -> None:
    for cls in (
        InvalidCredentials,
        InvalidMfaCode,
        RateLimited,
        TemporarilyBlocked,
        GarminUnavailable,
        TokenRejected,
        GarminProtocolError,
    ):
        assert issubclass(cls, GarminError)
        assert str(cls()) == cls.message
        assert cls.message.isascii()
