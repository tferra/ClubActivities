import pytest

from garmin_hub.config import Settings
from garmin_hub.security.ratelimit import Outcome, decide


@pytest.fixture
def s():
    return Settings(public_url="https://x.test")


def test_pair_block(s) -> None:
    assert decide(4, 0, 0, s).outcome is Outcome.ALLOW
    assert decide(5, 0, 0, s).outcome is Outcome.BLOCKED_PAIR


def test_ip_block(s) -> None:
    assert decide(0, 19, 0, s).outcome is Outcome.ALLOW
    assert decide(0, 20, 0, s).outcome is Outcome.BLOCKED_IP


@pytest.mark.parametrize(
    ("failures", "delay"), [(49, 0.0), (50, 0.5), (51, 1.0), (70, 10.0), (500, 10.0)]
)
def test_email_soft_delay(s, failures, delay) -> None:
    decision = decide(0, 0, failures, s)
    assert decision.delay == delay
    assert decision.outcome is Outcome.ALLOW  # nunca bloqueo total por correo


def test_soft_limit_crossed_once(s) -> None:
    assert decide(0, 0, 50, s).crossed_soft_limit(s)
    assert not decide(0, 0, 51, s).crossed_soft_limit(s)


def test_custom_thresholds() -> None:
    s = Settings(public_url="https://x.test", login_pair_max_failures=3)
    assert decide(3, 0, 0, s).outcome is Outcome.BLOCKED_PAIR
