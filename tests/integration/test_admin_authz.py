import uuid

import pytest

pytestmark = pytest.mark.integration

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


def call(client, csrf_for, method, path):
    if method == "GET":
        return client.get(path, follow_redirects=False)
    return client.post(path, data={"csrf_token": csrf_for(client)}, follow_redirects=False)


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_normal_user_404(method, path, client, make_user, login_as, csrf_for) -> None:
    user = make_user()
    login_as(client, user)
    path = path.format(uid=user.user_id, iid=uuid.uuid4())
    assert call(client, csrf_for, method, path).status_code == 404


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_anonymous_303(method, path, client, csrf_for) -> None:
    path = path.format(uid=uuid.uuid4(), iid=uuid.uuid4())
    r = call(client, csrf_for, method, path)
    assert r.status_code == 303 and r.headers["location"] == "/login"


@pytest.mark.parametrize(("method", "path"), [r for r in ADMIN_ROUTES if "{" in r[1]])
def test_unknown_ids_404_for_admin(method, path, client, make_user, login_as, csrf_for) -> None:
    login_as(client, make_user(role="admin"))
    path = path.format(uid=uuid.uuid4(), iid=uuid.uuid4())
    assert call(client, csrf_for, method, path).status_code == 404
    assert (
        call(client, csrf_for, method, path.replace(path.split("/")[3], "no-es-uuid")).status_code
        == 404
    )
