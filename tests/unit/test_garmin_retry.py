import random

import pytest

from garmin_hub.garmin.client import (
    GarminProtocolError,
    GarminUnavailable,
    RateLimited,
    TokenRejected,
)
from garmin_hub.garmin.retry import call_with_backoff


class Flaky:
    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


@pytest.mark.parametrize("error", [RateLimited, GarminUnavailable])
def test_retries_transient_with_exponential_jittered_backoff(error) -> None:
    sleeps: list[float] = []
    fn = Flaky([error(), error()])
    assert call_with_backoff(fn, max_retries=2, sleep=sleeps.append, rng=random.Random(1)) == "ok"
    assert fn.calls == 3
    assert 0.5 <= sleeps[0] <= 1.5
    assert 1.0 <= sleeps[1] <= 3.0


def test_gives_up_after_max_retries() -> None:
    sleeps: list[float] = []
    fn = Flaky([RateLimited(), RateLimited(), RateLimited()])
    with pytest.raises(RateLimited):
        call_with_backoff(fn, max_retries=2, sleep=sleeps.append, rng=random.Random(1))
    assert fn.calls == 3
    assert len(sleeps) == 2


def test_zero_retries() -> None:
    fn = Flaky([GarminUnavailable()])
    with pytest.raises(GarminUnavailable):
        call_with_backoff(fn, max_retries=0, sleep=lambda s: None, rng=random.Random(1))
    assert fn.calls == 1


@pytest.mark.parametrize("error", [TokenRejected, GarminProtocolError])
def test_definitive_errors_not_retried(error) -> None:
    sleeps: list[float] = []
    fn = Flaky([error()])
    with pytest.raises(error):
        call_with_backoff(fn, max_retries=2, sleep=sleeps.append, rng=random.Random(1))
    assert fn.calls == 1
    assert sleeps == []


def test_seeded_rng_is_deterministic() -> None:
    a: list[float] = []
    b: list[float] = []
    for out in (a, b):
        fn = Flaky([RateLimited(), RateLimited()])
        call_with_backoff(fn, max_retries=2, sleep=out.append, rng=random.Random(42))
    assert a == b
