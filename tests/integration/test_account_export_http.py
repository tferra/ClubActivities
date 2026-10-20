import json

import pytest

from garmin_hub.accounts import export

pytestmark = pytest.mark.integration


def test_export(client, make_user, login_as, audit_rows, monkeypatch) -> None:
    monkeypatch.setattr(export, "_SECTIONS", dict(export._SECTIONS))
    export.register_export_section("extra", lambda conn, user_id: {"ok": True})
    user = make_user()
    login_as(client, user)
    r = client.get("/cuenta/exportar")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"] == 'attachment; filename="garmin-hub-export.json"'
    data = json.loads(r.text)
    assert data["format_version"] == 1
    assert "exported_at" in data
    profile = data["profile"]
    assert profile["email"] == user.email
    assert profile["role"] == "user" and profile["status"] == "active"
    assert {"display_name", "created_at", "last_login_at"} <= set(profile)
    assert isinstance(data["audit_events"], list)
    assert data["extra"] == {"ok": True}
    for forbidden in ("password_hash", "argon2", "session_hash", "code_hash"):
        assert forbidden not in r.text
    event = audit_rows("user.data_exported")[0]
    assert event["details"]["sections"] == ["profile", "audit_events", "extra"]


def test_duplicate_section_rejected(monkeypatch) -> None:
    monkeypatch.setattr(export, "_SECTIONS", dict(export._SECTIONS))
    with pytest.raises(ValueError):
        export.register_export_section("profile", lambda conn, user_id: None)
