from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests


class _AuditStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[dict] = []

    def add(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.events)


@pytest.fixture()
def server() -> tuple[str, _AuditStore]:
    store = _AuditStore()

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: object, *, request_id: str) -> None:
            b = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Request-Id", request_id)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self) -> None:  # noqa: N802
            request_id = str(uuid.uuid4())
            path = (self.path or "").split("?", 1)[0]
            auth = (self.headers.get("Authorization") or "").strip()

            actor = "anonymous"
            if auth.startswith("Bearer "):
                tok = auth[len("Bearer ") :].strip()
                if tok == "viewer-token":
                    actor = "viewer"
                elif tok == "admin-token":
                    actor = "admin"
                else:
                    actor = "unknown"

            # Always log with request_id, but never store raw auth.
            store.add(
                {
                    "ts": time.time(),
                    "request_id": request_id,
                    "actor": actor,
                    "resource": path,
                    "auth": "present" if actor != "anonymous" else "missing",
                }
            )

            if path == "/metrics/device.model":
                if actor in ("viewer", "admin"):
                    self._send_json(200, {"value": "eyeSight-DEMO"}, request_id=request_id)
                else:
                    self._send_json(401, {"error": "unauthorized"}, request_id=request_id)
                return

            if path == "/audit/events":
                if actor == "admin":
                    self._send_json(200, {"events": store.snapshot()}, request_id=request_id)
                else:
                    self._send_json(403, {"error": "forbidden"}, request_id=request_id)
                return

            self._send_json(404, {"error": "not_found"}, request_id=request_id)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = httpd.server_address

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}", store
    finally:
        httpd.shutdown()


def test_traceability_request_id_and_audit_linkage(server: tuple[str, _AuditStore]) -> None:
    base_url, _store = server

    # Make two requests; each must have a request id.
    r1 = requests.get(
        f"{base_url}/metrics/device.model",
        headers={"Authorization": "Bearer viewer-token"},
        timeout=5,
    )
    r2 = requests.get(
        f"{base_url}/metrics/device.model",
        headers={"Authorization": "Bearer viewer-token"},
        timeout=5,
    )

    rid1 = r1.headers.get("X-Request-Id")
    rid2 = r2.headers.get("X-Request-Id")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert rid1 and rid2
    assert rid1 != rid2

    # Pull audit events and ensure request_ids show up and can be linked.
    r3 = requests.get(
        f"{base_url}/audit/events",
        headers={"Authorization": "Bearer admin-token"},
        timeout=5,
    )
    assert r3.status_code == 200
    events = (r3.json() or {}).get("events")
    assert isinstance(events, list) and events

    event_ids = {e.get("request_id") for e in events}
    assert rid1 in event_ids
    assert rid2 in event_ids

    # Ensure audit events do not store raw Authorization header values.
    for e in events:
        s = json.dumps(e)
        assert "Bearer" not in s
        assert "viewer-token" not in s
        assert "admin-token" not in s
