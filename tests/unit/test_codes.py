import re

from garmin_hub.security.codes import ALPHABET, code_hash, generate_code, normalize_code


def test_generate_format() -> None:
    code = generate_code()
    assert re.fullmatch(r"[0-9A-Z]{4}(-[0-9A-Z]{4}){4}", code)
    assert set(code.replace("-", "")) <= set(ALPHABET)
    assert len({generate_code() for _ in range(100)}) == 100


def test_normalize() -> None:
    assert normalize_code(" abcd-efgh ijkm-nopq-rstv ") == "ABCDEFGH1JKMN0PQRSTV"
    assert normalize_code("o0-Il") == "0011"


def test_hash_equivalent_variants(keys) -> None:
    code = generate_code()
    variants = [code, code.lower(), code.replace("-", ""), " " + code.replace("-", " ")]
    hashes = {code_hash(keys, v) for v in variants}
    assert len(hashes) == 1
    assert len(hashes.pop()) == 32
