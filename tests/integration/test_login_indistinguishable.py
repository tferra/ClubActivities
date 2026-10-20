import re

import pytest

from garmin_hub.security import passwords

pytestmark = pytest.mark.integration


class CountingHasher:
    def __init__(self, real) -> None:
        self.real = real
        self.calls = 0

    def verify(self, *args, **kwargs):
        self.calls += 1
        return self.real.verify(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.real, name)


def normalize(html: str) -> str:
    return re.sub(r"[0-9a-f]{64}", "TOKEN", html)


def test_failures_indistinguishable(make_client, csrf_for, make_user, monkeypatch) -> None:
    active = make_user()
    deactivated = make_user(status="deactivated")
    blocked = make_user()
    attacker = make_client("198.51.100.77")
    for _ in range(5):
        attacker.post(
            "/login",
            data={
                "email": blocked.email,
                "password": "mal-mal-mal-mal",
                "csrf_token": csrf_for(attacker),
            },
        )
    counter = CountingHasher(passwords._hasher)
    monkeypatch.setattr(passwords, "_hasher", counter)
    cases = [
        (make_client("192.0.2.1"), active.email, "mal-mal-mal-mal"),
        (make_client("192.0.2.2"), "nadie@club.test", "mal-mal-mal-mal"),
        (make_client("192.0.2.3"), deactivated.email, deactivated.password),
        (attacker, blocked.email, blocked.password),
    ]
    responses = []
    for client, email, password in cases:
        before = counter.calls
        r = client.post(
            "/login", data={"email": email, "password": password, "csrf_token": csrf_for(client)}
        )
        assert counter.calls - before == 1
        responses.append(r)
    assert {r.status_code for r in responses} == {422}
    bodies = {normalize(r.text) for r in responses}
    assert len(bodies) == 1
