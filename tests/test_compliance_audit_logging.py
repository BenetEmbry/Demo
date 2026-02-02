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

        def _actor_from_token(self) -> str:
            auth = (self.headers.get("Authorization") or "").strip()
            if not auth.startswith("Bearer "):
                return "anonymous"
            token = auth[len("Bearer ") :].strip()
            if token == "admin-token":
                return "admin"
            if token == "viewer-token":
                return "viewer"
            return "unknown"

        def do_GET(self) -> None:  # noqa: N802
            request_id = str(uuid.uuid4())
            actor = self._actor_from_token()
            path = (self.path or "").split("?", 1)[0]

            # Simple authz rules for demo
            decision = "deny"
            status = 401
            payload: object = {"error": "unauthorized"}

            if actor in ("admin", "viewer"):
                status = 200
                decision = "allow"
                payload = {"value": "eyeSight-DEMO"}

            if path == "/audit/events":
                if actor != "admin":
                    status = 403
                    decision = "deny"
                    payload = {"error": "forbidden"}
                else:
                    status = 200
                    decision = "allow"
                    payload = {"events": store.snapshot()}

            store.add(
                {
                    "ts": time.time(),
                    "request_id": request_id,
                    "actor": actor,
                    "action": "GET",
                    "resource": path,
                    "decision": decision,
                    # Mask token: do NOT store raw auth header.
                    "auth": "present" if actor != "anonymous" else "missing",
                    "client_ip": self.client_address[0] if self.client_address else None,
                }
            )

            self._send_json(status, payload, request_id=request_id)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = httpd.server_address

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}", store
    finally:
        httpd.shutdown()


def test_access_auditing_and_logging_validation(server: tuple[str, _AuditStore]) -> None:
    base_url, store = server

    # Make both an allowed request and a denied request.
    r1 = requests.get(
        f"{base_url}/metrics/device.model",
        headers={"Authorization": "Bearer viewer-token"},
        timeout=5,
    )
    assert r1.status_code == 200
    assert r1.headers.get("X-Request-Id")

    r2 = requests.get(
        f"{base_url}/metrics/device.model",
        headers={"Authorization": "Bearer bad-token"},
        timeout=5,
    )
    assert r2.status_code in (401, 403)
    assert r2.headers.get("X-Request-Id")

    # Admin can retrieve audit events.
    r3 = requests.get(
        f"{base_url}/audit/events",
        headers={"Authorization": "Bearer admin-token"},
        timeout=5,
    )
    assert r3.status_code == 200
    payload = r3.json()

    events = payload.get("events")
    assert isinstance(events, list) and events

    # Validate required audit fields (SOC2/ISO-friendly shape)
    for e in events:
        assert "ts" in e
        assert "request_id" in e
        assert "actor" in e
        assert "action" in e
        assert "resource" in e
        assert "decision" in e
        assert "auth" in e

        # Logging/masking: raw tokens must not appear.
        s = json.dumps(e)
        assert "viewer-token" not in s
        assert "bad-token" not in s
        assert "admin-token" not in s

    # Also ensure the server-side store has the same shape.
    assert store.snapshot()
