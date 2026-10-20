from garmin_hub.keys import LABELS, derive_keys, hmac_digest


def test_subkeys_distinct_deterministic_and_secret_bound() -> None:
    a = derive_keys(b"a" * 32)
    values = [getattr(a, label.replace("-", "_")) for label in LABELS]
    assert len(set(values)) == len(LABELS) == 6
    assert derive_keys(b"a" * 32) == a
    b = derive_keys(b"b" * 32)
    assert all(getattr(a, f) != getattr(b, f) for f in a.__dataclass_fields__)


def test_hmac_digest() -> None:
    assert len(hmac_digest(b"k", "x")) == 32
    assert hmac_digest(b"k", "x") != hmac_digest(b"k", "y")
