import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from garmin_hub.garmin.client import MfaPending
from garmin_hub.garmin.pending import PendingLogin, PendingLoginRegistry, RegistryFull


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class Client:
    def __init__(self) -> None:
        self.discarded: list[MfaPending] = []

    def discard(self, pending: MfaPending) -> None:
        self.discarded.append(pending)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def registry(clock, client) -> PendingLoginRegistry:
    return PendingLoginRegistry(ttl=timedelta(minutes=5), clock=clock, client=client)


def add(registry, user_id, **kwargs) -> PendingLogin:
    options = {"purpose": "link", "garmin_account_id": None, "alias": "Mía"}
    options.update(kwargs)
    return registry.add(user_id=user_id, pending=MfaPending(handle=object()), **options)


def test_add_and_get_by_attempt_and_user(registry) -> None:
    user = uuid4()
    entry = add(registry, user)
    assert len(entry.attempt_id) >= 20
    assert registry.get(entry.attempt_id, user) is entry
    assert registry.get(entry.attempt_id, uuid4()) is None
    assert registry.get("otro", user) is None


def test_expires_after_ttl(registry, clock, client) -> None:
    user = uuid4()
    entry = add(registry, user)
    assert entry.expires_at == clock.now + timedelta(minutes=5)
    clock.now += timedelta(minutes=5)
    assert registry.get(entry.attempt_id, user) is entry
    clock.now += timedelta(seconds=1)
    assert registry.get(entry.attempt_id, user) is None
    assert client.discarded == [entry.pending]


def test_new_attempt_discards_previous_of_same_user(registry, client) -> None:
    user = uuid4()
    first = add(registry, user)
    second = add(registry, user)
    assert registry.get(first.attempt_id, user) is None
    assert registry.get(second.attempt_id, user) is second
    assert client.discarded == [first.pending]


def test_pop_removes_without_discard(registry, client) -> None:
    user = uuid4()
    entry = add(registry, user)
    assert registry.pop(entry.attempt_id, user) is entry
    assert registry.get(entry.attempt_id, user) is None
    assert client.discarded == []


def test_discard_for_user_and_account(registry, client) -> None:
    user, other = uuid4(), uuid4()
    account = uuid4()
    mine = add(registry, user)
    theirs = add(registry, other, purpose="reauth", garmin_account_id=account, alias=None)
    registry.discard_for_user(user)
    assert registry.get(mine.attempt_id, user) is None
    registry.discard_for_account(account)
    assert registry.get(theirs.attempt_id, other) is None
    assert client.discarded == [mine.pending, theirs.pending]


def test_global_cap(clock, client) -> None:
    registry = PendingLoginRegistry(
        ttl=timedelta(minutes=5), clock=clock, client=client, max_entries=2
    )
    add(registry, uuid4())
    add(registry, uuid4())
    with pytest.raises(RegistryFull):
        add(registry, uuid4())
    assert len(client.discarded) == 1  # el intento rechazado se libera


def test_entries_hold_no_email_or_password() -> None:
    names = {f.name for f in dataclasses.fields(PendingLogin)}
    assert not {n for n in names if "email" in n or "password" in n}
