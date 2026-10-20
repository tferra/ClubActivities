import threading

import pytest
from sqlalchemy import func, select

from garmin_hub.accounts.invitations import InvalidCode, redeem_invitation
from garmin_hub.db.schema import app_user

pytestmark = [pytest.mark.integration, pytest.mark.mssql]


def test_same_code_twice_creates_one_user(engine, keys, clock, make_invitation) -> None:
    code = make_invitation()
    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            with engine.begin() as conn:
                redeem_invitation(
                    conn,
                    code=code,
                    display_name="Ana",
                    password="luna-llena-sobre-el-puerto",
                    keys=keys,
                    ip_prefix=None,
                    now=clock(),
                )
            results.append("ok")
        except InvalidCode:
            results.append("invalid")
        except Exception as exc:
            results.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(app_user)).scalar_one() == 1
