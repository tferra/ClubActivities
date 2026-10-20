"""SC-002: ningún secreto de Garmin en claro en la base de datos, los logs ni las respuestas."""

import re

import pytest
from sqlalchemy import LargeBinary, String, Unicode, select
from sqlalchemy.types import BINARY

from garmin_hub.db.schema import audit_event, metadata
from garmin_hub.garmin.fake import FAKE_MFA_CODE

pytestmark = pytest.mark.integration

PROFILE_ID = "987654321"
EMAIL = f"ok+{PROFILE_ID}@example.test"
MFA_EMAIL = "mfa+987654322@example.test"
PASSWORD = "Contraseña-Centinela-Garmin-42"
WRONG_PASSWORD = "Otra-Contraseña-Centinela-43"
WRONG_CODE = "908172"
TOKEN = "TOKEN-CENTINELA-di-refresh"
SENTINELS = [EMAIL, MFA_EMAIL, PASSWORD, WRONG_PASSWORD, WRONG_CODE, TOKEN, FAKE_MFA_CODE]
ATTEMPT_RE = re.compile(r'name="attempt_id" value="([^"]+)"')


def test_full_cycle_leaves_no_plaintext(
    client, garmin_user, form_post, fake_garmin, engine, captured_logs, garmin_rows, clock
) -> None:
    fake_garmin.password = PASSWORD
    fake_garmin.token_extra = TOKEN
    bodies: list[str] = []

    def post(path, data=None, **kwargs):
        r = form_post(client, path, data, **kwargs)
        bodies.append(r.text)
        return r

    def link(alias, email, password=PASSWORD):
        return post(
            "/cuentas-garmin/vincular",
            {"alias": alias, "garmin_email": email, "garmin_password": password},
        )

    link("Principal", EMAIL, WRONG_PASSWORD)  # credenciales rechazadas
    assert link("Principal", EMAIL).status_code == 303
    r = link("Bici", MFA_EMAIL)
    attempt_id = ATTEMPT_RE.search(r.text).group(1)
    post("/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": WRONG_CODE})
    assert (
        post(
            "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": FAKE_MFA_CODE}
        ).status_code
        == 303
    )
    principal, bici = (r["garmin_account_id"] for r in garmin_rows())

    reauth = f"/cuentas-garmin/{principal}/reautenticar"
    post(reauth, {"garmin_email": EMAIL, "garmin_password": WRONG_PASSWORD})
    assert post(reauth, {"garmin_email": EMAIL, "garmin_password": PASSWORD}).status_code == 303
    fake_garmin.script_verify(int(PROFILE_ID), "renew")
    post(f"/cuentas-garmin/{principal}/comprobar", headers={"HX-Request": "true"})
    bodies.append(client.get("/cuentas-garmin").text)
    bodies.append(client.get("/").text)
    bodies.append(client.get("/cuenta/exportar").text)
    clock.advance(minutes=2)
    assert (
        post(
            f"/cuentas-garmin/{principal}/desvincular",
            {"mode": "keep", "confirmation": "Principal"},
        ).status_code
        == 303
    )
    assert (
        post(
            f"/cuentas-garmin/{bici}/desvincular", {"mode": "delete", "confirmation": "Bici"}
        ).status_code
        == 303
    )

    texts: list[str] = []
    blobs: list[bytes] = []
    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            columns = [
                c
                for c in table.columns
                if isinstance(c.type, String | Unicode | BINARY | LargeBinary)
            ]
            if not columns:
                continue
            for row in conn.execute(select(*columns)):
                for value in row:
                    if isinstance(value, bytes):
                        blobs.append(value)
                    elif value is not None:
                        texts.append(str(value))
        details = [d for (d,) in conn.execute(select(audit_event.c.details))]
    assert texts and blobs, "el ciclo debería haber dejado filas y accesos cifrados"
    for sentinel in SENTINELS:
        assert not any(sentinel in t for t in texts), sentinel
        assert not any(sentinel.encode() in b for b in blobs), sentinel
    # El profileId solo vive en garmin_account.garmin_profile_id (FR-028a).
    assert not any(PROFILE_ID in t for t in texts)
    assert not any(PROFILE_ID in d for d in details if d)

    logs = list(captured_logs)
    assert logs, "el ciclo debería haber generado logs"
    for sentinel in [*SENTINELS, PROFILE_ID]:
        assert not any(sentinel in line for line in logs), sentinel
        assert not any(sentinel in body for body in bodies), sentinel
