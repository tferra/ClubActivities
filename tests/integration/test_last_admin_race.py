import threading

import pytest
from sqlalchemy import func, select

from garmin_hub.accounts.users import Conflict, deactivate_user
from garmin_hub.db.schema import app_user

pytestmark = [pytest.mark.integration, pytest.mark.mssql]


def test_mutual_deactivation_keeps_one_admin(engine, make_user, clock) -> None:
    a, b = make_user(role="admin"), make_user(role="admin")
    barrier = threading.Barrier(2)

    def worker(actor, target) -> None:
        barrier.wait()
        try:
            with engine.begin() as conn:
                deactivate_user(
                    conn,
                    admin_id=actor.user_id,
                    user_id=target.user_id,
                    ip_prefix=None,
                    now=clock(),
                )
        except Conflict:
            pass

    threads = [threading.Thread(target=worker, args=p) for p in ((a, b), (b, a))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with engine.connect() as conn:
        active = conn.execute(
            select(func.count())
            .select_from(app_user)
            .where(app_user.c.role == "admin", app_user.c.status == "active")
        ).scalar_one()
    assert active >= 1
