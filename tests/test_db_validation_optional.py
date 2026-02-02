from __future__ import annotations

import os

import pytest

from regression.db_validation import maybe_validate_backend_db


def test_backend_db_validation_optional() -> None:
    # Only runs if DB_MODE is configured.
    if not (os.getenv("DB_MODE") or "").strip():
        pytest.skip("DB_MODE not set")

    maybe_validate_backend_db()
