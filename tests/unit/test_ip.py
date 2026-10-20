from types import SimpleNamespace

from garmin_hub.security.ip import UNKNOWN, client_ip, ip_hmac, ip_prefix


def test_ip_prefix() -> None:
    assert ip_prefix("203.0.113.57") == "203.0.113.0/24"
    assert ip_prefix("2001:db8:1:2::5") == "2001:db8:1::/48"
    assert ip_prefix("::ffff:203.0.113.57") == "203.0.113.0/24"
    assert ip_prefix("testclient") == UNKNOWN
    assert ip_prefix("") == UNKNOWN


def test_ip_hmac(keys) -> None:
    digest = ip_hmac(keys, "203.0.113.57")
    assert len(digest) == 32
    assert digest == ip_hmac(keys, "203.0.113.57")
    assert b"203.0.113.57" not in digest


def test_client_ip() -> None:
    assert client_ip(SimpleNamespace(client=SimpleNamespace(host="198.51.100.4"))) == "198.51.100.4"
    assert client_ip(SimpleNamespace(client=None)) == UNKNOWN
