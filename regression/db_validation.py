from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DbCheck:
    name: str
    query: str
    expected: Any | None = None


def run_sqlite_checks(db_path: str, checks: list[DbCheck]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        for c in checks:
            cur = conn.execute(c.query)
            row = cur.fetchone()
            value = None if row is None else row[0]
            if c.expected is not None:
                assert value == c.expected, f"DB check '{c.name}': expected {c.expected!r}, got {value!r}"
            else:
                assert value is not None, f"DB check '{c.name}': query returned no rows"
    finally:
        conn.close()


def maybe_validate_backend_db() -> None:
    """Optional DB validation hook.

    Enable by setting:
    - DB_MODE=sqlite
    - DB_SQLITE_PATH=/path/to.db

    Then create a YAML file listing checks and set:
    - DB_CHECKS_FILE=path/to/db_checks.yaml

    If not configured, this does nothing.
    """

    mode = (os.getenv("DB_MODE") or "").strip().lower()
    if not mode:
        return

    if mode != "sqlite":
        raise RuntimeError(f"Unsupported DB_MODE: {mode!r} (only 'sqlite' is supported in the demo)")

    db_path = (os.getenv("DB_SQLITE_PATH") or "").strip()
    if not db_path:
        raise RuntimeError("DB_SQLITE_PATH is required when DB_MODE=sqlite")

    checks_file = (os.getenv("DB_CHECKS_FILE") or "").strip()
    if not checks_file:
        raise RuntimeError("DB_CHECKS_FILE is required when DB_MODE=sqlite")

    import yaml

    with open(checks_file, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}

    checks: list[DbCheck] = []
    for item in spec.get("checks") or []:
        checks.append(
            DbCheck(
                name=str(item.get("name") or item.get("query") or "db_check"),
                query=str(item["query"]),
                expected=item.get("expected"),
            )
        )

    run_sqlite_checks(db_path, checks)
