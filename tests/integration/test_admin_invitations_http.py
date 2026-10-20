import re

import pytest

pytestmark = pytest.mark.integration

CODE_RE = re.compile(r"[0-9A-Z]{4}(?:-[0-9A-Z]{4}){4}")


@pytest.fixture
def admin_client(client, make_user, login_as):
    login_as(client, make_user(role="admin"))
    return client


def test_create_and_list(admin_client, csrf_for) -> None:
    r = admin_client.post(
        "/admin/invitaciones",
        data={"email": "ana@club.test", "note": "Equipo A", "csrf_token": csrf_for(admin_client)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    code = CODE_RE.search(r.text).group(0)
    assert "no se volverá a mostrar" in r.text
    # La fila nueva llega fuera de banda dentro de <template>; si no, el navegador descarta
    # el <tbody> fuera de una tabla y las filas aparecen sueltas (htmx 2).
    oob = re.search(r"<template>\s*<tbody id=\"invitation-rows\" hx-swap-oob=\"true\">", r.text)
    assert oob is not None
    page = admin_client.get("/admin/invitaciones")
    assert page.status_code == 200
    assert "ana@club.test" in page.text
    assert "Pendiente" in page.text
    assert "Equipo A" in page.text
    assert code not in page.text
    assert page.headers["cache-control"] == "no-store"


def test_validation_422_spanish(admin_client, csrf_for) -> None:
    r = admin_client.post(
        "/admin/invitaciones",
        data={"email": "mal", "csrf_token": csrf_for(admin_client)},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 422
    assert "El correo no tiene un formato válido." in r.text
    r = admin_client.post(
        "/admin/invitaciones",
        data={"email": "b@club.test", "ttl_days": "99", "csrf_token": csrf_for(admin_client)},
    )
    assert r.status_code == 422
    assert "La caducidad debe estar entre 1 y 30 días." in r.text


def test_normal_user_gets_404(client, make_user, login_as, csrf_for) -> None:
    login_as(client, make_user())
    assert client.get("/admin/invitaciones").status_code == 404
    r = client.post(
        "/admin/invitaciones", data={"email": "x@club.test", "csrf_token": csrf_for(client)}
    )
    assert r.status_code == 404


def test_anonymous_redirected(client) -> None:
    r = client.get("/admin/invitaciones", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_post_without_csrf_403(admin_client) -> None:
    r = admin_client.post("/admin/invitaciones", data={"email": "x@club.test"})
    assert r.status_code == 403
    assert "La sesión del formulario ha caducado" in r.text
