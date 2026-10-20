import pytest
from sqlalchemy import LargeBinary, String, Unicode, select
from sqlalchemy.types import BINARY

from garmin_hub.db.schema import metadata
from tests.conftest import TEST_DB_URL, TEST_SESSION_SECRET
from tests.integration.cycle import IP, run_cycle

pytestmark = pytest.mark.integration


def test_no_plaintext_secrets(
    engine, keys, clock, make_client, csrf_for, monkeypatch, captured_logs, settings
) -> None:
    known = run_cycle(engine, keys, clock, make_client, csrf_for, monkeypatch)
    db_password = TEST_DB_URL.split(":")[2].split("@")[0]
    secrets = [
        *known.passwords,
        *known.codes,
        *[c.replace("-", "") for c in known.codes],
        *[s for s in known.session_ids if s],
        *known.csrf_tokens,
        TEST_SESSION_SECRET.decode(),
        db_password,
        IP,
    ]
    assert len(known.session_ids) >= 3 and all(known.session_ids)

    texts: list[str] = []
    blobs: list[bytes] = []
    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            columns = [
                c
                for c in table.columns
                if isinstance(c.type, (String, Unicode, BINARY, LargeBinary))
            ]
            for row in conn.execute(select(*columns)):
                for value in row:
                    if isinstance(value, bytes):
                        blobs.append(value)
                    elif value is not None:
                        texts.append(str(value))
    assert texts, "el ciclo debería haber dejado filas"
    for secret in secrets:
        assert not any(secret in t for t in texts), secret
        assert not any(secret.encode() in b for b in blobs), secret

    logs = list(captured_logs)
    log_dir = settings.log_dir
    if log_dir.exists():
        logs += [p.read_text(encoding="utf-8") for p in log_dir.glob("*.log*")]
    assert logs, "el ciclo debería haber generado logs"
    for secret in [*secrets, *known.emails]:
        assert not any(secret in line for line in logs), secret
