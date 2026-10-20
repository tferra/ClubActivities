"""SQL de SQL Server de `0002_garmin_accounts`, generado sin conectarse (T026)."""

import re

from garmin_hub.db.migrate import render_sql


def _index_sql(sql: str, name: str) -> str:
    match = re.search(rf"CREATE UNIQUE INDEX \[?{name}\]?[^;]*", sql)
    assert match, name
    return match.group(0)


def test_filtered_indexes_have_where_clause() -> None:
    sql = render_sql("gh", "0001_user_access:0002_garmin_accounts")
    assert "WHERE status IN ('valid', 'reauth_required', 'error')" in _index_sql(
        sql, "UX_garmin_account_profile_active"
    )
    for name in ("UX_garmin_account_user_profile", "UX_garmin_account_user_alias"):
        assert "WHERE status IN ('valid', 'reauth_required', 'error', 'unlinked')" in _index_sql(
            sql, name
        )
    assert "CK_garmin_account_status_fields" in sql
    assert "VARBINARY(max)" in sql
    assert "UPDATE gh.alembic_version SET version_num='0002_garmin_accounts'" in sql
