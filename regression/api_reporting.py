from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from regression.redaction import redact_text, redact_url


@dataclass(frozen=True)
class ApiCall:
    method: str
    url: str
    status_code: int | None
    ok: bool
    elapsed_ms: float
    error: str | None


_LOCK = threading.Lock()
_CALLS: list[ApiCall] = []


def record_api_call(
    *,
    method: str,
    url: str,
    status_code: int | None,
    ok: bool,
    elapsed_ms: float,
    error: str | None,
) -> None:
    with _LOCK:
        _CALLS.append(
            ApiCall(
                method=method,
                url=url,
                status_code=status_code,
                ok=ok,
                elapsed_ms=float(elapsed_ms),
                error=error,
            )
        )


def get_api_calls() -> list[ApiCall]:
    with _LOCK:
        return list(_CALLS)


def summarize_calls(calls: list[ApiCall]) -> dict[str, Any]:
    label_rules_raw = (os.getenv("API_LABEL_RULES") or "").strip()
    label_rules: list[tuple[str, re.Pattern[str]]] = []
    if label_rules_raw:
        # Format: "Label=regex;Other=regex2" (regex matches full URL)
        for part in label_rules_raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            label, rx = part.split("=", 1)
            label = label.strip()
            rx = rx.strip()
            if not label or not rx:
                continue
            try:
                label_rules.append((label, re.compile(rx)))
            except re.error:
                continue

    def label_for(url: str) -> str:
        for label, rx in label_rules:
            if rx.search(url):
                return label
        return "(unlabeled)"

    by_url: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}

    for c in calls:
        safe_url = redact_url(c.url)
        label = label_for(safe_url)

        entry = by_url.setdefault(
            safe_url,
            {
                "label": label,
                "method": c.method,
                "url": safe_url,
                "count": 0,
                "ok_count": 0,
                "error_count": 0,
                "status_codes": {},
                "p50_ms": None,
                "p95_ms": None,
                "max_ms": None,
            },
        )

        lentry = by_label.setdefault(
            label,
            {
                "label": label,
                "count": 0,
                "ok_count": 0,
                "error_count": 0,
                "status_codes": {},
            },
        )

        entry["count"] += 1
        lentry["count"] += 1
        if c.ok and c.error is None and (c.status_code is None or 200 <= c.status_code < 400):
            entry["ok_count"] += 1
            lentry["ok_count"] += 1
        else:
            entry["error_count"] += 1
            lentry["error_count"] += 1

        sc = "none" if c.status_code is None else str(c.status_code)
        entry["status_codes"][sc] = int(entry["status_codes"].get(sc, 0)) + 1
        lentry["status_codes"][sc] = int(lentry["status_codes"].get(sc, 0)) + 1

    # latency stats
    for url, entry in by_url.items():
        latencies = [c.elapsed_ms for c in calls if redact_url(c.url) == url]
        latencies.sort()
        if not latencies:
            continue

        def pct(p: float) -> float:
            i = int(round((p / 100.0) * (len(latencies) - 1)))
            return float(latencies[max(0, min(i, len(latencies) - 1))])

        entry["p50_ms"] = pct(50)
        entry["p95_ms"] = pct(95)
        entry["max_ms"] = float(latencies[-1])

    return {
        "total_calls": len(calls),
        "total_errors": sum(1 for c in calls if not c.ok or c.error is not None),
        "labels": sorted(by_label.values(), key=lambda x: (x["error_count"], x["count"], x["label"]), reverse=True),
        "endpoints": sorted(by_url.values(), key=lambda x: (x["error_count"], x["count"], x["url"]), reverse=True),
    }


def write_api_report(path: str) -> str:
    calls = get_api_calls()

    safe_calls = []
    for c in calls:
        safe_calls.append(
            {
                **asdict(c),
                "url": redact_url(c.url),
                "error": redact_text(c.error) if c.error else None,
            }
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "python": {
            "time": time.time(),
        },
        "summary": summarize_calls(calls),
        "calls": safe_calls,
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)

    return path
