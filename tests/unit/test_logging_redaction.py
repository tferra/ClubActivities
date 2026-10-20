import json
import logging

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from garmin_hub.logging_setup import AccessLogMiddleware, JsonFormatter, RedactingFilter


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(RedactingFilter())
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def lines(self) -> list[str]:
        return [self.format(r) for r in self.records]


@pytest.fixture
def handler():
    h = ListHandler()
    logger = logging.getLogger("garmin_hub.test")
    logger.addHandler(h)
    logger.setLevel(logging.DEBUG)
    yield h
    logger.removeHandler(h)


SENSITIVE = [
    "password",
    "pass",
    "secret",
    "token",
    "code",
    "cookie",
    "authorization",
    "session",
    "csrf",
    "email",
    "ip",
    "client",
    "remote_addr",
    "db_url",
]


@pytest.mark.parametrize("key", SENSITIVE)
def test_extra_sensitive_keys_masked(handler, key) -> None:
    logging.getLogger("garmin_hub.test").info("evento", extra={key: "VALOR-SECRETO"})
    line = handler.lines()[0]
    assert "VALOR-SECRETO" not in line
    assert json.loads(line)[key] == "***"


def test_dict_args_masked(handler) -> None:
    logging.getLogger("garmin_hub.test").info("p=%(password)s", {"password": "hunter2hunter2"})
    assert "hunter2hunter2" not in handler.lines()[0]


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        ("usuario ana@club.test entra", "ana@club.test"),
        ("código ABCD-EFGH-JKMN-PQRS-TVWX", "ABCD-EFGH-JKMN-PQRS-TVWX"),
        ("desde 203.0.113.57 ok", "203.0.113.57"),
        ("desde 2001:db8:1:2::5 ok", "2001:db8:1:2::5"),
        ("url mssql+pyodbc://u:secreto@h/db", "secreto"),
    ],
)
def test_message_patterns_masked(handler, text, leak) -> None:
    logging.getLogger("garmin_hub.test").warning(text)
    assert leak not in handler.lines()[0]


def test_prefix_and_times_kept(handler) -> None:
    logging.getLogger("garmin_hub.test").info("red 203.0.113.0/24 a las 12:30:45")
    msg = json.loads(handler.lines()[0])["msg"]
    assert "203.0.113.0/24" in msg
    assert "12:30:45" in msg


def test_ip_prefix_extra_not_masked(handler) -> None:
    logging.getLogger("garmin_hub.test").info("x", extra={"ip_prefix": "203.0.113.0/24"})
    assert json.loads(handler.lines()[0])["ip_prefix"] == "203.0.113.0/24"


def test_json_one_line_per_event(handler) -> None:
    log = logging.getLogger("garmin_hub.test")
    log.info("uno\ndos")
    log.info("tres")
    lines = handler.lines()
    assert len(lines) == 2
    assert all("\n" not in line for line in lines)
    assert json.loads(lines[0])["msg"] == "uno\ndos"


def test_access_log_middleware(handler) -> None:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/x", ok)])
    wrapped = AccessLogMiddleware(app, logger_name="garmin_hub.test.access")
    client = TestClient(wrapped, client=("203.0.113.57", 4000))
    client.get("/x?code=ABCD&email=a@b.test")
    data = json.loads(handler.lines()[-1])
    assert data["method"] == "GET"
    assert data["path"] == "/x"
    assert data["status"] == 200
    assert data["ip_prefix"] == "203.0.113.0/24"
    line = handler.lines()[-1]
    assert "203.0.113.57" not in line
    assert "code=" not in line and "a@b.test" not in line


THIRD_PARTY_SENTINELS = [
    "ana.garmin@example.test",
    "pw-CENTINELA-123",
    "eyJ-TOKEN-CENTINELA",
    "987654321",
]


@pytest.mark.parametrize("name", ["garminconnect", "garminconnect.client", "curl_cffi"])
def test_third_party_logs_are_scrubbed(settings, name) -> None:
    from garmin_hub.logging_setup import THIRD_PARTY_MESSAGE, configure_logging

    configure_logging(settings)
    assert logging.getLogger("garminconnect").level == logging.ERROR
    assert logging.getLogger("curl_cffi").level == logging.ERROR
    email, password, token, profile_id = THIRD_PARTY_SENTINELS
    logger = logging.getLogger(name)
    logger.warning("aviso con %s", email)  # por debajo de ERROR: se descarta
    try:
        raise RuntimeError(f"fallo {token} profileId={profile_id}")
    except RuntimeError:
        logger.error(
            "login %s:%s profileId=" + profile_id, email, password, exc_info=True, stack_info=True
        )
    for handler in logging.getLogger("garmin_hub").handlers:
        handler.flush()
    content = (settings.log_dir / "garmin-hub.log").read_text(encoding="utf-8")
    for sentinel in THIRD_PARTY_SENTINELS:
        assert sentinel not in content
    lines = [json.loads(line) for line in content.splitlines() if line.strip()]
    assert any(
        line["msg"] == THIRD_PARTY_MESSAGE and line["logger"] == name and line["level"] == "ERROR"
        for line in lines
    )
