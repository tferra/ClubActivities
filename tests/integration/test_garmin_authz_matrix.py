"""Matriz de autorización de `/cuentas-garmin` (US3, FR-014, FR-015, SC-004).

Recorre dinámicamente las rutas del router: las que añadan las historias posteriores entran
solas en la matriz.
"""

import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from garmin_hub.db.schema import audit_event, garmin_account, garmin_token
from garmin_hub.security.csrf import require_csrf
from garmin_hub.web.routes import garmin_accounts

pytestmark = pytest.mark.integration

FORM = {
    "alias": "Intruso",
    "garmin_email": "ok+1@example.test",
    "garmin_password": "correcta",
    "mode": "delete",
    "confirmation": "Suya",
    "accept": "1",
}


def routes() -> list[tuple[str, str]]:
    found = []
    for route in garmin_accounts.router.routes:
        if isinstance(route, APIRoute):
            found += [(method, route.path) for method in sorted(route.methods - {"HEAD"})]
    return found


def account_routes() -> list[tuple[str, str]]:
    return [(m, p) for m, p in routes() if "{account_id}" in p]


def snapshot(engine) -> tuple:
    with engine.connect() as conn:
        accounts = [tuple(r) for r in conn.execute(select(garmin_account))]
        tokens = [tuple(r) for r in conn.execute(select(garmin_token))]
        audits = conn.execute(select(func.count()).select_from(audit_event)).scalar_one()
    return sorted(accounts, key=str), sorted(tokens, key=str), audits


@pytest.fixture
def two_users(make_client, make_user, login_as, accept_notice, make_garmin_account):
    a, b = make_user(), make_user()
    for user in (a, b):
        accept_notice(user.user_id)
    client_a = make_client()
    login_as(client_a, a)
    b_account = make_garmin_account(b.user_id, alias="Suya", profile_id=77)
    return client_a, a, b, b_account


CONTRACT = {
    ("GET", "/cuentas-garmin"),
    ("GET", "/cuentas-garmin/aviso"),
    ("POST", "/cuentas-garmin/aviso"),
    ("GET", "/cuentas-garmin/vincular"),
    ("POST", "/cuentas-garmin/vincular"),
    ("POST", "/cuentas-garmin/mfa"),
    ("POST", "/cuentas-garmin/mfa/cancelar"),
    ("GET", "/cuentas-garmin/{account_id}/reautenticar"),
    ("POST", "/cuentas-garmin/{account_id}/reautenticar"),
    ("POST", "/cuentas-garmin/{account_id}/comprobar"),
    ("GET", "/cuentas-garmin/{account_id}/desvincular"),
    ("POST", "/cuentas-garmin/{account_id}/desvincular"),
    ("GET", "/cuentas-garmin/{account_id}/borrar-datos"),
    ("POST", "/cuentas-garmin/{account_id}/borrar-datos"),
    ("POST", "/cuentas-garmin/{account_id}/reintentar-borrado"),
}


def test_router_matches_http_contract() -> None:
    assert set(routes()) == CONTRACT


def test_router_requires_regular_user_and_csrf() -> None:
    deps = [d.dependency for d in garmin_accounts.router.dependencies]
    assert require_csrf in deps
    assert garmin_accounts.require_regular_user in deps


def test_other_users_account_is_indistinguishable(
    two_users, form_post, engine, fake_garmin
) -> None:
    client_a, _, _, b_account = two_users
    before = snapshot(engine)
    for method, path in account_routes():
        bodies = set()
        for raw_id in (str(b_account), str(uuid.uuid4()), "abc", str(b_account).upper()):
            url = path.format(account_id=raw_id)
            if method == "GET":
                r = client_a.get(url, follow_redirects=False)
            else:
                r = form_post(client_a, url, FORM)
            assert r.status_code == 404, (method, url, r.status_code)
            bodies.add(r.text)
        assert len(bodies) == 1, (method, path)
    assert snapshot(engine) == before
    assert fake_garmin.calls == []


def test_list_shows_only_own_accounts(two_users, make_garmin_account) -> None:
    client_a, a, _, _ = two_users
    make_garmin_account(a.user_id, alias="Mía")
    text = client_a.get("/cuentas-garmin").text
    assert "Mía" in text and "Suya" not in text


def test_admin_gets_404_everywhere(
    make_client, make_user, login_as, accept_notice, form_post, two_users, fake_garmin
) -> None:
    _, _, _, b_account = two_users
    admin = make_user(role="admin")
    accept_notice(admin.user_id)
    client = make_client()
    login_as(client, admin)
    for method, path in routes():
        url = path.format(account_id=b_account)
        r = client.get(url) if method == "GET" else form_post(client, url, FORM)
        assert r.status_code == 404, (method, url)
    assert fake_garmin.calls == []


def test_anonymous_redirected_to_login(client, csrf_for, two_users) -> None:
    _, _, _, b_account = two_users
    for method, path in routes():
        url = path.format(account_id=b_account)
        r = client.request(
            method, url, data={"csrf_token": csrf_for(client)}, follow_redirects=False
        )
        assert r.status_code == 303 and r.headers["location"] == "/login", (method, url)


def test_post_without_csrf_is_403(two_users, engine) -> None:
    client_a, _, _, b_account = two_users
    before = snapshot(engine)
    for method, path in routes():
        if method == "POST":
            r = client_a.post(path.format(account_id=b_account), data=FORM)
            assert r.status_code == 403, path
    assert snapshot(engine) == before
