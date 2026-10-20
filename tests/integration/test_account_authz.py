import pytest
from sqlalchemy import select

from garmin_hub.db.schema import app_user

pytestmark = pytest.mark.integration


def test_user_cannot_modify_other(client, csrf_for, make_user, login_as, engine) -> None:
    a, b = make_user(), make_user()
    login_as(client, a)
    r = client.post(
        "/cuenta/nombre",
        data={
            "display_name": "Hackeado",
            "user_id": str(b.user_id),
            "csrf_token": csrf_for(client),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with engine.connect() as conn:
        names = dict(conn.execute(select(app_user.c.user_id, app_user.c.display_name)).all())
    assert names[b.user_id] == b.display_name
    assert names[a.user_id] == "Hackeado"


@pytest.mark.parametrize("path", ["/cuenta", "/cuenta/exportar", "/cuenta/eliminar"])
def test_anonymous_redirected(client, path) -> None:
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_export_contains_only_own_data(client, make_user, login_as, csrf_for) -> None:
    a, b = make_user(), make_user()
    other = client.__class__(client.app, base_url="https://testserver")
    login_as(other, b)
    other.post("/cuenta/nombre", data={"display_name": "Bea", "csrf_token": csrf_for(other)})
    login_as(client, a)
    text = client.get("/cuenta/exportar").text
    assert b.email not in text
    assert str(b.user_id) not in text
