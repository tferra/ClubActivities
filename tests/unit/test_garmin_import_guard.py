"""Solo `garmin/garminconnect_client.py` puede importar la librería (constitución III, R1)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "garmin_hub"
ALLOWED = SRC / "garmin" / "garminconnect_client.py"
FORBIDDEN = ("garminconnect", "curl_cffi")


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_library_imported_only_in_adapter() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if path == ALLOWED:
            continue
        roots = _imported_roots(ast.parse(path.read_text(encoding="utf-8")))
        if roots & set(FORBIDDEN):
            offenders.append(str(path.relative_to(SRC)))
    assert offenders == []


def test_adapter_does_import_the_library() -> None:
    assert "garminconnect" in _imported_roots(ast.parse(ALLOWED.read_text(encoding="utf-8")))
