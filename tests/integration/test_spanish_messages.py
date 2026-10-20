from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from garmin_hub.security import passwords
from garmin_hub.web.templating import TEMPLATES_DIR

pytestmark = pytest.mark.integration


def test_generic_messages(client, csrf_for) -> None:
    r = client.post(
        "/login", data={"email": "a@b.test", "password": "x", "csrf_token": csrf_for(client)}
    )
    assert "Correo o contraseña incorrectos." in r.text
    r = client.post("/alta/codigo", data={"code": "x", "csrf_token": csrf_for(client)})
    assert "El código no es válido o ha caducado." in r.text
    r = client.post(
        "/restablecer",
        data={
            "email": "a@b.test",
            "code": "x",
            "password": "p" * 12,
            "password_confirm": "p" * 12,
            "csrf_token": csrf_for(client),
        },
    )
    assert "El código no es válido o ha caducado." in r.text


def test_password_messages_spanish() -> None:
    for name in dir(passwords):
        if name.startswith("MSG_"):
            message = getattr(passwords, name)
            assert message.startswith(("La contraseña", "Las contraseñas")), name


def test_error_pages(app, client) -> None:
    r = client.get("/no-existe")
    assert r.status_code == 404 and "Página no encontrada" in r.text
    r = client.post("/login", data={})
    assert r.status_code == 403 and "La sesión del formulario ha caducado" in r.text
    r = client.delete("/cuenta")
    assert r.status_code == 405 and r.text == "Método no permitido."

    def boom() -> None:
        raise RuntimeError("fallo")

    app.add_api_route("/__boom", boom)
    r = TestClient(app, base_url="https://testserver", raise_server_exceptions=False).get("/__boom")
    assert r.status_code == 500 and "Algo ha fallado" in r.text


def test_all_pages_are_spanish() -> None:
    base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
    assert '<html lang="es">' in base
    for path in Path(TEMPLATES_DIR).rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        # Los textos versionados del aviso de datos (feature 002) se incluyen en notice.html.
        is_fragment = path.name.startswith("_") or path.name.startswith("notice_v")
        if path.name != "base.html" and not is_fragment:
            assert text.startswith('{% extends "base.html" %}'), path.name


def test_garmin_messages_spanish_without_library_text() -> None:
    from garmin_hub.garmin_accounts import errors
    from garmin_hub.web.templating import GARMIN_STATUS_LABELS

    messages = {n: getattr(errors, n) for n in dir(errors) if n.startswith("MSG_")}
    assert len(messages) >= 25
    technical = ("garminconnect", "curl", "http", "429", "403", "token", "exception", "error:")
    for name, message in messages.items():
        assert message[0].isupper() and message.rstrip().endswith((".", "»")), name
        assert not any(word in message.lower() for word in technical), name
    assert set(GARMIN_STATUS_LABELS.values()) == {
        "Válida",
        "Requiere reautenticación",
        "Error",
        "Desvinculada (datos conservados)",
        "Borrando datos… (no se pudo completar)",
    }
    assert errors.message_for(errors.TokenRejected()) == errors.MSG_TOKEN_REJECTED
