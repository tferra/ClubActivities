from fastapi.testclient import TestClient

from garmin_hub.config import Settings
from garmin_hub.security.headers import CSP
from garmin_hub.web.app import create_app

EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def test_headers_https(settings, secrets) -> None:
    client = TestClient(create_app(settings, secrets, engine=object()))
    r = client.get("/healthz")
    assert r.text == "ok"
    assert CSP == EXPECTED_CSP
    assert r.headers["content-security-policy"] == EXPECTED_CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "same-origin"
    assert r.headers["permissions-policy"] == "geolocation=(), camera=(), microphone=()"
    assert r.headers["strict-transport-security"] == "max-age=31536000"
    assert "cache-control" not in r.headers


def test_no_hsts_on_http(tmp_path, secrets) -> None:
    s = Settings(public_url="http://localhost:8000", log_dir=tmp_path)
    r = TestClient(create_app(s, secrets, engine=object())).get("/healthz")
    assert "strict-transport-security" not in r.headers
