import pytest

from garmin_hub.security import passwords as pw


@pytest.fixture
def common(common_passwords):
    return pw.load_common_passwords(common_passwords)


def check(password, common, email="anaperez@club.test", name="Ana Martínez"):
    return pw.validate_password(password, email=email, display_name=name, common=common)


def test_length_rules(common) -> None:
    assert check("a1b2c3d4e5f", common) == pw.MSG_TOO_SHORT
    assert check("x" * 64 + "y" * 65, common) == pw.MSG_TOO_LONG
    assert check("ab" + "\uff43" * 9, common) == pw.MSG_TOO_SHORT  # NFKC
    assert check("tres palabras largas", common) is None


def test_common_and_repeated(common) -> None:
    assert check("CorrectHorseBattery", common) == pw.MSG_COMMON
    assert check("zzzzzzzzzzzzzz", common) == pw.MSG_REPEATED


def test_contains_email_local_part(common) -> None:
    assert check("xxANAPEREZxx-azul", common) == pw.MSG_CONTAINS_EMAIL


def test_contains_name_word(common) -> None:
    assert check("mi clave MARTÍNEZ 2026", common) == pw.MSG_CONTAINS_NAME


def test_no_false_positives(common) -> None:
    # parte local de menos de 4 caracteres y fragmento de palabra del nombre
    assert check("ana-y-su-perro-azul", common, email="ana@club.test") is None
    assert check("mart-y-su-perro-azul", common) is None


def test_messages_are_spanish(common) -> None:
    for message in (pw.MSG_TOO_SHORT, pw.MSG_COMMON, pw.MSG_CONTAINS_NAME, pw.MSG_REPEATED):
        assert message.startswith("La contraseña")


def test_hash_and_verify() -> None:
    h = pw.hash_password("una clave larga y segura")
    assert h.startswith("$argon2id$")
    assert pw.verify_password(h, "una clave larga y segura")
    assert not pw.verify_password(h, "otra clave larga y segura")
    assert not pw.verify_password("not-a-hash", "x")
    assert pw.verify_dummy("lo que sea") is False
    assert pw.needs_rehash(h) is False


def test_vendored_list_loads() -> None:
    common = pw.load_common_passwords()
    assert len(common) > 1000
    assert all(len(p) >= 12 for p in list(common)[:100])
