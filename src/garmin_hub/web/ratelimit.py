"""Límite de intentos en las rutas: comprobación en el pool y retardo sin ocupar hilos (R10)."""

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from garmin_hub.security.ratelimit import Decision, Kind, check_attempts, record_attempt
from garmin_hub.web.deps import now, transaction


def _check(request: Request, email: str | None, ip: str, kind: Kind) -> Decision:
    state = request.app.state
    with transaction(request) as conn:
        return check_attempts(
            conn,
            email=email,
            ip=ip,
            kind=kind,
            keys=state.keys,
            settings=state.settings,
            now=now(request),
        )


async def check_and_wait(request: Request, *, email: str | None, ip: str, kind: Kind) -> Decision:
    """Calcula la decisión y espera el retardo fuera de la transacción y del pool de hilos."""
    decision = await run_in_threadpool(_check, request, email, ip, kind)
    if decision.delay > 0:
        await request.app.state.sleep(decision.delay)
    return decision


def record(request: Request, *, email: str | None, ip: str, kind: Kind, succeeded: bool) -> None:
    with transaction(request) as conn:
        record_attempt(
            conn,
            email=email,
            ip=ip,
            kind=kind,
            succeeded=succeeded,
            keys=request.app.state.keys,
            now=now(request),
        )
