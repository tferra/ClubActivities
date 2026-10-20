import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from garmin_hub.db.schema import app_user
from garmin_hub.security.csrf import require_csrf
from garmin_hub.web.app import route_modules

pytestmark = pytest.mark.integration

# Las rutas de la feature 002 tienen su propia matriz (test_garmin_authz_matrix.py).
GARMIN_PREFIX = "/cuentas-garmin"
PUBLIC = {"/login", "/logout", "/alta", "/alta/codigo", "/restablecer", "/healthz"}
USER_ROUTES = [
    ("GET", "/"),
    ("GET", "/cuenta"),
    ("POST", "/cuenta/nombre"),
    ("POST", "/cuenta/contrasena"),
    ("GET", "/cuenta/exportar"),
    ("GET", "/cuenta/eliminar"),
    ("POST", "/cuenta/eliminar"),
]
ADMIN_ROUTES = [
    ("GET", "/admin/usuarios"),
    ("GET", "/admin/invitaciones"),
    ("POST", "/admin/invitaciones"),
    ("POST", "/admin/usuarios/{uid}/desactivar"),
    ("POST", "/admin/usuarios/{uid}/reactivar"),
    ("POST", "/admin/usuarios/{uid}/restablecimiento"),
    ("GET", "/admin/usuarios/{uid}/eliminar"),
    ("POST", "/admin/usuarios/{uid}/eliminar"),
    ("POST", "/admin/usuarios/{uid}/reintentar-borrado"),
    ("POST", "/admin/invitaciones/{iid}/revocar"),
]
ALL_POST = [
    *[r for r in USER_ROUTES + ADMIN_ROUTES if r[0] == "POST"],
    ("POST", "/login"),
    ("POST", "/logout"),
    ("POST", "/alta/codigo"),
    ("POST", "/alta"),
    ("POST", "/restablecer"),
]


def snapshot(engine):
    with engine.connect() as conn:
        return {r.user_id: tuple(r) for r in conn.execute(select(app_user))}


def module_routes() -> list[APIRoute]:
    return [r for m in route_modules() for r in m.router.routes if isinstance(r, APIRoute)]


def test_contract_covers_all_routes() -> None:
    declared = {p for _, p in USER_ROUTES + ADMIN_ROUTES} | PUBLIC
    actual = {
        r.path.replace("{user_id}", "{uid}").replace("{invitation_id}", "{iid}")
        for r in module_routes()
        if not r.path.startswith(GARMIN_PREFIX)
    } | {"/healthz"}
    assert actual == declared


def test_every_unsafe_route_requires_csrf() -> None:
    routes = module_routes()
    unsafe = [r for r in routes if r.methods - {"GET", "HEAD"}]
    assert len([r for r in unsafe if not r.path.startswith(GARMIN_PREFIX)]) == len(ALL_POST)
    for route in unsafe:
        assert any(d.dependency is require_csrf for d in route.dependencies), route.path


@pytest.mark.parametrize(("method", "path"), USER_ROUTES)
def test_anonymous_redirected(method, path, client, csrf_for) -> None:
    r = client.request(method, path, data={"csrf_token": csrf_for(client)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


@pytest.mark.parametrize(("method", "path"), ALL_POST)
def test_post_without_csrf_403(method, path, client, make_user, login_as) -> None:
    login_as(client, make_user())
    path = path.format(uid=uuid.uuid4(), iid=uuid.uuid4())
    assert client.post(path, data={"x": "1"}).status_code == 403


def test_user_a_cannot_touch_b_and_role_unchanged(
    make_client, make_user, login_as, csrf_for, engine
) -> None:
    a, b = make_user(), make_user()
    admin = make_user(role="admin")
    ca = make_client()
    login_as(ca, a)
    before = snapshot(engine)
    for method, path in ADMIN_ROUTES:
        path = path.format(uid=b.user_id, iid=uuid.uuid4())
        data = {
            "csrf_token": csrf_for(ca),
            "role": "admin",
            "user_id": str(b.user_id),
            "confirmation_email": b.email,
            "email": "x@club.test",
        }
        r = ca.request(method, path, data=data, follow_redirects=False)
        assert r.status_code == 404
    for path, data in [
        ("/cuenta/nombre", {"display_name": "A2"}),
        ("/cuenta/contrasena", {"current_password": "x", "password": "y", "password_confirm": "y"}),
    ]:
        ca.post(
            path,
            data={**data, "user_id": str(b.user_id), "role": "admin", "csrf_token": csrf_for(ca)},
        )
    after = snapshot(engine)
    assert after[b.user_id] == before[b.user_id]
    assert after[admin.user_id] == before[admin.user_id]
    with engine.connect() as conn:
        roles = dict(conn.execute(select(app_user.c.user_id, app_user.c.role)).all())
    assert roles == {a.user_id: "user", b.user_id: "user", admin.user_id: "admin"}
