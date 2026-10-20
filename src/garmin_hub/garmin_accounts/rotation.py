"""Recifrado de los accesos con la clave vigente (`garmin-hub key reencrypt`, research R5)."""

from datetime import datetime

from sqlalchemy import Engine, select, update

from garmin_hub.db.schema import garmin_token
from garmin_hub.security.token_cipher import TokenCipher, UndecryptableToken

_c = garmin_token.c


def reencrypt_tokens(engine: Engine, cipher: TokenCipher, now: datetime) -> tuple[int, int]:
    """Recifra cada acceso que no use la clave vigente, una transacción por fila (idempotente).

    Devuelve `(recifrados, pendientes)`: los pendientes usan una versión que ya no está
    configurada y no se tocan. Nunca registra accesos ni claves.
    """
    current = cipher.current_version
    with engine.connect() as conn:
        account_ids = list(
            conn.execute(select(_c.garmin_account_id).where(_c.key_version != current)).scalars()
        )
    done = pending = 0
    for account_id in account_ids:
        with engine.begin() as conn:
            row = conn.execute(
                select(_c.ciphertext, _c.key_version)
                .where(_c.garmin_account_id == account_id)
                .with_hint(garmin_token, "WITH (UPDLOCK)", "mssql")
            ).first()
            if row is None or row.key_version == current:
                continue
            try:
                plain = cipher.decrypt(row.ciphertext, row.key_version)
            except UndecryptableToken:
                pending += 1
                continue
            ciphertext, version = cipher.encrypt(plain)
            conn.execute(
                update(garmin_token)
                .where(_c.garmin_account_id == account_id, _c.key_version == row.key_version)
                .values(ciphertext=ciphertext, key_version=version, updated_at=now)
            )
            done += 1
    return done, pending
