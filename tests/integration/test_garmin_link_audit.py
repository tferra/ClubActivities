import pytest

from garmin_hub.garmin.fake import FAKE_MFA_CODE, FAKE_PASSWORD

pytestmark = pytest.mark.integration


def link(form_post, client, email, password=FAKE_PASSWORD, alias="Mi Alias Personal"):
    return form_post(
        client,
        "/cuentas-garmin/vincular",
        {"alias": alias, "garmin_email": email, "garmin_password": password},
    )


def test_linked_event(client, garmin_user, form_post, audit_rows, garmin_rows) -> None:
    link(form_post, client, "ok+31@example.test")
    (event,) = audit_rows("garmin.account_linked")
    account_id = str(garmin_rows()[0]["garmin_account_id"])
    assert event["details"] == {"garmin_account_id": account_id, "recovered": False, "mfa": False}
    assert event["actor_user_id"] == event["subject_user_id"] == garmin_user.user_id


def test_linked_with_mfa_event(client, garmin_user, form_post, audit_rows) -> None:
    import re

    r = link(form_post, client, "mfa+32@example.test")
    attempt_id = re.search(r'name="attempt_id" value="([^"]+)"', r.text).group(1)
    form_post(client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": "000000"})
    form_post(client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": FAKE_MFA_CODE})
    (event,) = audit_rows("garmin.account_linked")
    assert event["details"]["mfa"] is True
    assert [e["details"]["reason"] for e in audit_rows("garmin.link_failed")] == ["bad_mfa"]


def test_failure_reasons(
    client, garmin_user, form_post, audit_rows, make_garmin_account, clock
) -> None:
    make_garmin_account(garmin_user.user_id, alias="Ocupado", profile_id=40)
    link(form_post, client, "ok+33@example.test", "mala")
    link(form_post, client, "ratelimit@example.test")
    link(form_post, client, "blocked@example.test")
    link(form_post, client, "down@example.test")
    link(form_post, client, "ok+34@example.test", alias="ocupado")
    link(form_post, client, "ok+40@example.test", alias="Otro")
    for _ in range(4):
        link(form_post, client, "ok+33@example.test", "mala")
    link(form_post, client, "ok+35@example.test")
    reasons = [e["details"]["reason"] for e in audit_rows("garmin.link_failed")]
    assert reasons == [
        "bad_credentials",
        "rate_limited",
        "blocked",
        "unavailable",
        "alias_taken",
        "already_linked_self",
        *["bad_credentials"] * 4,
        "throttled",
    ]


def test_expired_and_limit_reasons(
    client, garmin_user, form_post, audit_rows, make_garmin_account, clock
) -> None:
    import re

    r = link(form_post, client, "mfa+36@example.test")
    attempt_id = re.search(r'name="attempt_id" value="([^"]+)"', r.text).group(1)
    clock.advance(minutes=6)
    form_post(client, "/cuentas-garmin/mfa", {"attempt_id": attempt_id, "mfa_code": FAKE_MFA_CODE})
    for _ in range(10):
        make_garmin_account(garmin_user.user_id)
    link(form_post, client, "ok+37@example.test", alias="Once")
    reasons = [e["details"]["reason"] for e in audit_rows("garmin.link_failed")]
    assert reasons == ["mfa_expired", "limit_reached"]


def test_linked_elsewhere_reason(
    client, garmin_user, form_post, audit_rows, make_client, make_user, login_as, accept_notice
):
    link(form_post, client, "ok+38@example.test")
    bea = make_user()
    accept_notice(bea.user_id)
    other = make_client()
    login_as(other, bea)
    link(form_post, other, "ok+38@example.test")
    (failed,) = audit_rows("garmin.link_failed")
    assert failed["details"] == {"reason": "linked_elsewhere"}
    assert failed["subject_user_id"] == bea.user_id


def test_details_never_contain_personal_data(client, garmin_user, form_post, audit_rows):
    link(form_post, client, "ok+987654@example.test")
    link(form_post, client, "ok+33@example.test", "contraseña-mala")
    for event in audit_rows():
        blob = str(event["details"])
        for leak in ("Mi Alias Personal", "@example.test", "987654", "contraseña-mala"):
            assert leak not in blob
