"""Ciclo completo de la feature con valores conocidos, compartido por los tests transversales."""

import re
from dataclasses import dataclass, field

from sqlalchemy import select

from garmin_hub.accounts import deletion
from garmin_hub.accounts.users import create_admin
from garmin_hub.db.schema import app_user
from garmin_hub.security.ratelimit import Kind, record_attempt
from garmin_hub.security.sessions import COOKIE_NAME

CODE_RE = re.compile(r"[0-9A-Z]{4}(?:-[0-9A-Z]{4}){4}")
IP = "203.0.113.57"


@dataclass
class Secrets:
    passwords: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    session_ids: list[str] = field(default_factory=list)
    csrf_tokens: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)


def run_cycle(engine, keys, clock, make_client, csrf_for, monkeypatch) -> Secrets:
    """admin create → invitación → alta → login → cambios → exportación → reset → borrado."""
    known = Secrets()
    admin_pw, ana_pw, ana_pw2, ana_pw3 = (
        "faro-azul-en-la-costa-norte",
        "luna-llena-sobre-el-puerto",
        "barco-velero-en-la-bahia",
        "tren-nocturno-hacia-el-sur",
    )
    known.passwords += [admin_pw, ana_pw, ana_pw2, ana_pw3]
    known.emails += ["admin@club.test", "ana@club.test"]

    with engine.begin() as conn:
        create_admin(
            conn, email="admin@club.test", display_name="Admin", password=admin_pw, now=clock()
        )

    def post(client, path, **data):
        headers = data.pop("_headers", None) or {}
        token = csrf_for(client)
        known.csrf_tokens.append(token)
        return client.post(
            path, data={**data, "csrf_token": token}, follow_redirects=False, headers=headers
        )

    admin = make_client(IP)
    post(admin, "/login", email="admin@club.test", password=admin_pw)
    known.session_ids.append(admin.cookies.get(COOKIE_NAME))

    # invitación revocada y otra usada
    r = post(admin, "/admin/invitaciones", email="revocada@club.test")
    known.codes.append(CODE_RE.search(r.text).group(0))
    page = admin.get("/admin/invitaciones").text
    revoke_id = re.search(r"/admin/invitaciones/([0-9a-f-]{36})/revocar", page).group(1)
    post(admin, f"/admin/invitaciones/{revoke_id}/revocar")
    r = post(admin, "/admin/invitaciones", email="ana@club.test", note="Equipo")
    code = CODE_RE.search(r.text).group(0)
    known.codes.append(code)

    ana = make_client(IP)
    post(ana, "/alta/codigo", code="ZZZZ-ZZZZ-ZZZZ-ZZZZ-ZZZZ")  # code_redeem_failed
    post(ana, "/alta/codigo", code=code)
    post(
        ana, "/alta", code=code, display_name="Ana Pérez", password=ana_pw, password_confirm=ana_pw
    )
    known.session_ids.append(ana.cookies.get(COOKIE_NAME))
    post(ana, "/logout")

    # fallos de login, límite global por correo y login correcto
    post(ana, "/login", email="ana@club.test", password="no-es-la-buena-clave")
    with engine.begin() as conn:
        for i in range(48):
            record_attempt(
                conn,
                email="ana@club.test",
                ip=f"192.0.2.{i}",
                kind=Kind.LOGIN,
                succeeded=False,
                keys=keys,
                now=clock(),
            )
    other = make_client("198.51.100.200")
    post(other, "/login", email="ana@club.test", password="no-es-la-buena-clave")
    post(ana, "/login", email="ana@club.test", password=ana_pw)
    known.session_ids.append(ana.cookies.get(COOKIE_NAME))

    post(ana, "/cuenta/nombre", display_name="Ana P.")
    post(
        ana,
        "/cuenta/contrasena",
        current_password="no-es-la-buena-clave",
        password=ana_pw2,
        password_confirm=ana_pw2,
    )
    post(
        ana,
        "/cuenta/contrasena",
        current_password=ana_pw,
        password=ana_pw2,
        password_confirm=ana_pw2,
    )
    ana.get("/cuenta/exportar")

    with engine.connect() as conn:
        ana_id = conn.execute(
            select(app_user.c.user_id).where(app_user.c.email == "ana@club.test")
        ).scalar_one()

    r = post(admin, f"/admin/usuarios/{ana_id}/restablecimiento", _headers={"HX-Request": "true"})
    reset_code = CODE_RE.search(r.text).group(0)
    known.codes.append(reset_code)
    anon = make_client(IP)
    post(
        anon,
        "/restablecer",
        email="ana@club.test",
        code=reset_code,
        password=ana_pw3,
        password_confirm=ana_pw3,
    )

    post(admin, f"/admin/usuarios/{ana_id}/desactivar", _headers={"HX-Request": "true"})
    post(admin, f"/admin/usuarios/{ana_id}/reactivar", _headers={"HX-Request": "true"})

    # borrado propio con un paso que falla y reintento del administrador
    post(ana, "/login", email="ana@club.test", password=ana_pw3)
    known.session_ids.append(ana.cookies.get(COOKIE_NAME))
    monkeypatch.setattr(deletion, "_STEPS", dict(deletion._STEPS))
    state = {"fail": True}

    def flaky(ctx, user_id):
        if state["fail"]:
            raise RuntimeError("fallo simulado")

    deletion.register_deletion_step("flaky", 900, flaky)
    post(ana, "/cuenta/eliminar", current_password=ana_pw3, confirmation="ELIMINAR")
    state["fail"] = False
    post(admin, f"/admin/usuarios/{ana_id}/reintentar-borrado", _headers={"HX-Request": "true"})
    post(admin, "/logout")
    return known
