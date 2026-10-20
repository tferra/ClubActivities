import pytest
from cryptography.fernet import Fernet

from garmin_hub.garmin.client import GarminTokens
from garmin_hub.security.token_cipher import TokenCipher, UndecryptableToken, parse_master_keys

K1 = Fernet.generate_key().decode()
K2 = Fernet.generate_key().decode()


def test_roundtrip_and_current_version() -> None:
    cipher = TokenCipher(parse_master_keys(f"1:{K1}"))
    ciphertext, version = cipher.encrypt(b'{"di_token": "abc"}')
    assert version == 1 == cipher.current_version
    assert b"abc" not in ciphertext
    assert cipher.decrypt(ciphertext, version) == b'{"di_token": "abc"}'


def test_current_is_highest_version_and_old_rows_still_decrypt() -> None:
    old = TokenCipher(parse_master_keys(f"1:{K1}"))
    ciphertext, version = old.encrypt(b"datos")
    both = TokenCipher(parse_master_keys(f"1:{K1},2:{K2}"))
    assert both.current_version == 2
    assert both.decrypt(ciphertext, version) == b"datos"
    new_ct, new_version = both.encrypt(b"datos")
    assert new_version == 2
    assert both.decrypt(new_ct, 2) == b"datos"


def test_unconfigured_version_is_undecryptable() -> None:
    cipher = TokenCipher(parse_master_keys(f"2:{K2}"))
    ciphertext, _ = TokenCipher(parse_master_keys(f"1:{K1}")).encrypt(b"x")
    with pytest.raises(UndecryptableToken):
        cipher.decrypt(ciphertext, 1)


def test_tampered_ciphertext_is_undecryptable() -> None:
    cipher = TokenCipher(parse_master_keys(f"1:{K1}"))
    ciphertext, version = cipher.encrypt(b"x")
    tampered = ciphertext[:-3] + (b"AAA" if ciphertext[-3:] != b"AAA" else b"BBB")
    with pytest.raises(UndecryptableToken):
        cipher.decrypt(tampered, version)
    wrong_key = TokenCipher(parse_master_keys(f"1:{K2}"))
    with pytest.raises(UndecryptableToken):
        wrong_key.decrypt(ciphertext, version)


def test_repr_never_shows_keys_or_content() -> None:
    cipher = TokenCipher(parse_master_keys(f"1:{K1},2:{K2}"))
    for text in (repr(cipher), str(cipher)):
        assert K1 not in text and K2 not in text
    tokens = GarminTokens(b'{"di_refresh_token": "REFRESH-SENTINEL"}')
    for text in (repr(tokens), str(tokens)):
        assert "REFRESH-SENTINEL" not in text


@pytest.mark.parametrize(
    "raw",
    [
        "",
        K1,
        f"x:{K1}",
        f"0:{K1}",
        f"-1:{K1}",
        f"1:{K1},1:{K2}",
        "1:no-es-una-clave",
        f"1:{K1},",
        f"1:{K1[:-4]}",
    ],
)
def test_parse_master_keys_rejects_bad_values_without_leaking(raw: str) -> None:
    with pytest.raises(ValueError) as exc:
        parse_master_keys(raw)
    if raw:
        assert K1 not in str(exc.value) and K2 not in str(exc.value)


def test_parse_master_keys_tolerates_spaces() -> None:
    keys = parse_master_keys(f" 1:{K1} , 3:{K2} ")
    assert sorted(keys) == [1, 3]
