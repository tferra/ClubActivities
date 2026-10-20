import pytest

pytestmark = pytest.mark.integration

GENERIC = "El código no es válido o ha caducado."


def test_ip_block_on_code_redeem(make_client, csrf_for, make_invitation, audit_rows) -> None:
    attacker = make_client("198.51.100.7")
    for _ in range(20):
        r = attacker.post(
            "/alta/codigo",
            data={"code": "AAAA-BBBB-CCCC-DDDD-EEEE", "csrf_token": csrf_for(attacker)},
        )
        assert r.status_code == 422
    code = make_invitation()
    r = attacker.post("/alta/codigo", data={"code": code, "csrf_token": csrf_for(attacker)})
    assert r.status_code == 422 and GENERIC in r.text
    assert audit_rows("auth.code_redeem_failed")[-1]["details"]["reason"] == "blocked_ip"
    other = make_client("192.0.2.10")
    r = other.post("/alta/codigo", data={"code": code, "csrf_token": csrf_for(other)})
    assert r.status_code == 200
