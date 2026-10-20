# Specification Quality Checklist: Vinculación y gestión de cuentas Garmin

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Validación 1/1: todo correcto.
- "Token", "MFA", "versión de la clave" y "clave maestra" son requisitos explícitos del
  propietario (constitución IV), no elecciones de implementación; el cifrado concreto (Fernet) y
  la librería de Garmin se deciden en `/speckit-plan`.
- Valores por defecto elegidos sin preguntar (revisables en `/speckit-clarify`): caducidad del
  intento MFA de 5 minutos; alias de 1 a 50 caracteres único por usuario; máximo 10 cuentas por
  usuario; 5 intentos fallidos de vinculación cada 15 minutos; una comprobación por minuto y
  cuenta; desvinculación con datos conservados como estado "Desvinculada (datos conservados)" con
  posibilidad de volver a vincular o borrar después; aviso de datos versionado.
- Dependencias: feature 001 (usuarios, auditoría, registro de pasos de borrado y de secciones de
  exportación). Las descargas de datos y los ficheros crudos llegan en features posteriores.
- Validación final de la implementación (T081, 2026-10-21):
  - `uv run ruff check` y `uv run ruff format --check`: limpios.
  - `uv run pytest`: 186 unitarios en verde.
  - `GARMIN_HUB_TEST_DB_URL=sqlite:// uv run pytest -m integration`: 286 en verde y 18 omitidos
    por requerir SQL Server (entre ellos la migración 0002 arriba y abajo, sus CHECK e índices
    filtrados y la concurrencia de la vinculación).
  - Quickstart, escenarios 0–17, con el cliente falso sobre SQLite (macOS): todos con el
    resultado esperado.
  - Pendiente:
    - la integración contra SQL Server y `garmin-hub db upgrade` / bajada a `0001_user_access` /
      subida sobre una base desechable;
    - el recorrido manual en Windows (PowerShell) y en Linux/WSL;
    - `pytest -m live` con una cuenta Garmin propia, que da el tiempo real de SC-001 (< 1 min).
      Con el cliente falso, la vinculación es inmediata.
