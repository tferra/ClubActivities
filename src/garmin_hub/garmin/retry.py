"""Backoff exponencial con jitter para las llamadas a Garmin (constitución III, research R11)."""

import random
from collections.abc import Callable

from garmin_hub.garmin.client import GarminUnavailable, RateLimited

BASE_DELAY_SECONDS = 1.0
FACTOR = 2.0
JITTER = 0.5

type Sleep = Callable[[float], object]


def jittered(seconds: float, rng: random.Random) -> float:
    """`seconds` ±50 %."""
    return seconds * rng.uniform(1 - JITTER, 1 + JITTER)


def call_with_backoff[T](
    fn: Callable[[], T], *, max_retries: int, sleep: Sleep, rng: random.Random
) -> T:
    """Reintenta `fn` solo ante `RateLimited` o `GarminUnavailable`, hasta `max_retries` veces."""
    attempt = 0
    while True:
        try:
            return fn()
        except (RateLimited, GarminUnavailable):
            if attempt >= max_retries:
                raise
        sleep(jittered(BASE_DELAY_SECONDS * FACTOR**attempt, rng))
        attempt += 1
