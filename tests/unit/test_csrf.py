import hashlib
import hmac
from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI, Form, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from garmin_hub.security import csrf


def test_session_token(keys) -> None:
    expected = hmac.new(keys.csrf, b"sid", hashlib.sha256).hexdigest()
    assert csrf.session_token(keys, "sid") == expected
    assert csrf.verify(expected, expected)
    assert not csrf.verify(expected, expected[:-1] + "0")
    assert not csrf.verify(expected, None)


def test_anon_pair(keys) -> None:
    nonce, token = csrf.new_anon_pair(keys)
    assert csrf.verify(csrf.anon_token(keys, nonce), token)
    assert not csrf.verify(csrf.anon_token(keys, nonce + "x"), token)
    assert not csrf.verify(csrf.anon_token(keys, nonce), token.upper())


def test_origin() -> None:
    assert csrf.origin_ok(None, "https://hub.test")
    assert csrf.origin_ok("https://hub.test", "https://hub.test")
    assert not csrf.origin_ok("https://evil.test", "https://hub.test")
    assert not csrf.origin_ok("http://hub.test", "https://hub.test")


def make_app(keys) -> FastAPI:
    app = FastAPI()
    app.state.keys = keys
    app.state.settings = SimpleNamespace(public_url="https://testserver")
    router = APIRouter()

    @router.post("/eco")
    def eco(nombre: str = Form()) -> PlainTextResponse:
        return PlainTextResponse(nombre)

    app.include_router(router, dependencies=[Depends(csrf.require_csrf)])

    @app.exception_handler(csrf.CsrfError)
    async def handler(request: Request, exc: csrf.CsrfError) -> PlainTextResponse:
        return PlainTextResponse("csrf", status_code=403)

    return app


def test_dependency_keeps_form_fields(keys) -> None:
    client = TestClient(make_app(keys), base_url="https://testserver")
    nonce, token = csrf.new_anon_pair(keys)
    client.cookies.set(csrf.ANON_COOKIE, nonce)
    ok = client.post("/eco", data={"nombre": "Ana", "csrf_token": token})
    assert ok.status_code == 200
    assert ok.text == "Ana"
    header = client.post("/eco", data={"nombre": "Eva"}, headers={"X-CSRF-Token": token})
    assert header.text == "Eva"
    assert client.post("/eco", data={"nombre": "Ana"}).status_code == 403
    bad_origin = client.post(
        "/eco", data={"nombre": "Ana", "csrf_token": token}, headers={"Origin": "https://evil"}
    )
    assert bad_origin.status_code == 403
