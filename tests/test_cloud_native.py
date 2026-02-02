from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from regression.api_contract import run_contract_checks


class _State:
    ready = True
    rate_limit_next = False


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Request-Id", str(uuid.uuid4()))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]

        if path == "/healthz":
            self._send_json(200, {"ok": True})
            return

        if path == "/livez":
            self._send_json(200, {"ok": True})
            return

        if path == "/readyz":
            if not _State.ready:
                self._send_json(503, {"ok": False})
                return
            self._send_json(200, {"ok": True})
            return

        if path == "/version":
            self._send_json(200, {"version": "1.2.3", "commit": "abc123"})
            return

        if path == "/metrics/device.model":
            if _State.rate_limit_next:
                _State.rate_limit_next = False
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "1")
                self.send_header("X-Request-Id", str(uuid.uuid4()))
                b = b'{"error":"rate_limited"}'
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return

            self._send_json(200, {"value": "eyeSight-DEMO"})
            return

        self._send_json(404, {"error": "not_found", "path": path})


@pytest.fixture()
def base_url() -> str:
    _State.ready = True
    _State.rate_limit_next = False

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()


def test_cloud_native_contract_runner(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    results = run_contract_checks("api_checks/demo_cloud_native_contract.yaml")
    assert [r.status_code for r in results] == [200, 200, 200, 200]


def test_readiness_transition(base_url: str) -> None:
    _State.ready = False
    r1 = requests.get(f"{base_url}/readyz", timeout=5)
    assert r1.status_code == 503

    _State.ready = True
    r2 = requests.get(f"{base_url}/readyz", timeout=5)
    assert r2.status_code == 200


def test_request_id_present_and_unique(base_url: str) -> None:
    r1 = requests.get(f"{base_url}/healthz", timeout=5)
    r2 = requests.get(f"{base_url}/healthz", timeout=5)

    rid1 = r1.headers.get("X-Request-Id")
    rid2 = r2.headers.get("X-Request-Id")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert rid1 and rid2
    assert rid1 != rid2


def test_rate_limit_retry_after_present(base_url: str) -> None:
    _State.rate_limit_next = True
    r = requests.get(f"{base_url}/metrics/device.model", timeout=5)
    assert r.status_code == 429
    assert r.headers.get("Retry-After")

    # Next request succeeds.
    r2 = requests.get(f"{base_url}/metrics/device.model", timeout=5)
    assert r2.status_code == 200
    assert (r2.json() or {}).get("value") == "eyeSight-DEMO"


def test_health_endpoint_fast(base_url: str) -> None:
    start = time.perf_counter()
    r = requests.get(f"{base_url}/healthz", timeout=5)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert r.status_code == 200
    assert elapsed_ms < 200.0
