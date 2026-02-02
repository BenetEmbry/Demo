from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import pytest
import yaml

from regression.sut import load_sut_adapter


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    type: str
    metric: str
    expected: dict[str, Any]
    source: dict[str, Any] | None = None


def _load_requirements(path: str) -> list[Requirement]:
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}

    items = doc.get("requirements") or []
    reqs: list[Requirement] = []

    for item in items:
        reqs.append(
            Requirement(
                id=str(item["id"]),
                title=str(item.get("title") or ""),
                type=str(item["type"]),
                metric=str(item["metric"]),
                expected=dict(item.get("expected") or {}),
                source=item.get("source"),
            )
        )

    return reqs


def _assert_requirement(requirement: Requirement, actual_value: Any) -> None:
    rtype = requirement.type

    if rtype == "presence":
        assert actual_value not in (None, "", [], {}), (
            f"{requirement.id}: expected presence for '{requirement.metric}', got {actual_value!r}"
        )
        return

    if rtype == "equals":
        expected_value = requirement.expected.get("value")
        assert actual_value == expected_value, (
            f"{requirement.id}: expected {expected_value!r} for '{requirement.metric}', got {actual_value!r}"
        )
        return

    if rtype == "one_of":
        options = requirement.expected.get("any_of")
        assert isinstance(options, list) and options, (
            f"{requirement.id}: expected.any_of must be a non-empty list"
        )
        assert actual_value in options, (
            f"{requirement.id}: expected one of {options!r} for '{requirement.metric}', got {actual_value!r}"
        )
        return

    if rtype == "range":
        if actual_value is None:
            raise AssertionError(
                f"{requirement.id}: expected numeric value for '{requirement.metric}', got None"
            )

        try:
            actual_num = float(actual_value)
        except Exception as e:  # noqa: BLE001
            raise AssertionError(
                f"{requirement.id}: expected numeric value for '{requirement.metric}', got {actual_value!r}"
            ) from e

        min_v = requirement.expected.get("min")
        max_v = requirement.expected.get("max")

        if min_v is not None:
            assert actual_num >= float(min_v), (
                f"{requirement.id}: expected >= {min_v} for '{requirement.metric}', got {actual_num}"
            )
        if max_v is not None:
            assert actual_num <= float(max_v), (
                f"{requirement.id}: expected <= {max_v} for '{requirement.metric}', got {actual_num}"
            )
        return

    if rtype == "regex":
        pattern = requirement.expected.get("pattern")
        assert isinstance(pattern, str) and pattern, (
            f"{requirement.id}: expected.pattern must be a non-empty string"
        )
        actual_s = "" if actual_value is None else str(actual_value)
        assert re.search(pattern, actual_s), (
            f"{requirement.id}: '{requirement.metric}' value {actual_s!r} did not match /{pattern}/"
        )
        return

    raise AssertionError(f"{requirement.id}: unknown requirement type '{rtype}'")


def test_datasheet_requirements() -> None:
    req_file = os.getenv("REQ_FILE", os.path.join("requirements", "eyesight_datasheet.yaml"))
    requirements = _load_requirements(req_file)

    # Keep the suite "green" until you add requirements.
    if not requirements:
        return

    try:
        sut = load_sut_adapter()
    except RuntimeError as e:
        pytest.skip(f"SUT not configured: {e}")

    for req in requirements:
        actual_value = sut.get_metric(req.metric)
        _assert_requirement(req, actual_value)
