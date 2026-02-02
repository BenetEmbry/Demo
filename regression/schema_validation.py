from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


@lru_cache(maxsize=128)
def load_json_schema(schema_path: str) -> Draft202012Validator:
    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_schema(schema_path: str, payload: Any) -> None:
    validator = load_json_schema(schema_path)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        msg = "; ".join(e.message for e in errors[:5])
        raise AssertionError(f"Schema validation failed for {schema_path}: {msg}")
