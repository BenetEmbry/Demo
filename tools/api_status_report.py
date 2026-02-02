from __future__ import annotations

import argparse
import json
import os
import time
from urllib.parse import urljoin

import requests

from regression.auth import load_auth_config_from_env


def _parse_paths(raw: str) -> list[str]:
    items = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part:
            items.append(part)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Check status of one or more API endpoints")
    parser.add_argument(
        "--base-url",
        default=os.getenv("SUT_BASE_URL") or "",
        help="Base URL (default: from SUT_BASE_URL)",
    )
    parser.add_argument(
        "--paths",
        default=os.getenv("API_STATUS_PATHS") or "/healthz",
        help="Comma-separated list of paths or full URLs (default: /healthz)",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=float(os.getenv("SUT_TIMEOUT_S") or "10"),
    )
    parser.add_argument(
        "--verify-tls",
        default=os.getenv("SUT_VERIFY_TLS") or "true",
        help="true/false (default: from SUT_VERIFY_TLS or true)",
    )
    args = parser.parse_args()

    base_url = (args.base_url or "").strip()
    verify_raw = str(args.verify_tls).strip().lower()
    verify_tls = verify_raw not in ("0", "false", "no")

    paths = _parse_paths(args.paths)
    if not paths:
        paths = ["/healthz"]

    results = []
    auth = load_auth_config_from_env()
    for p in paths:
        if p.startswith("http://") or p.startswith("https://"):
            url = p
        else:
            if not base_url:
                raise SystemExit("--base-url (or SUT_BASE_URL) is required for relative paths")
            url = urljoin(base_url.rstrip("/") + "/", p.lstrip("/"))

        start = time.perf_counter()
        status_code = None
        ok = False
        error = None
        try:
            url2 = auth.apply_url(url)
            headers = auth.apply_headers({"Accept": "application/json"})
            r = requests.get(url2, timeout=args.timeout_s, verify=verify_tls, headers=headers)
            status_code = r.status_code
            ok = bool(r.ok)
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        results.append(
            {
                "url": url,
                "effective_url": url2 if 'url2' in locals() else url,
                "status_code": status_code,
                "ok": ok,
                "elapsed_ms": elapsed_ms,
                "error": error,
            }
        )

    report = {
        "base_url": base_url or None,
        "results": results,
    }
    print(json.dumps(report, indent=2))

    # Exit non-zero if any endpoint failed
    if any((not r["ok"]) or r["error"] for r in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
