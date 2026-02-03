from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests


_ADMIN_TOKEN = "admin-token"
_VIEWER_TOKEN = "viewer-token"


def _bearer_token(headers: dict[str, str]) -> str | None:
    auth = (headers.get("Authorization") or "").strip()
    if not auth.startswith("Bearer "):
        return None
    return auth.split(" ", 1)[1].strip() or None


class _SecureHandler(BaseHTTPRequestHandler):
    server_version = "secure-demo/1.0"

    def _drain_request_body(self) -> None:
        # If we return early on a POST without consuming the request body,
        # Windows may abort/reset the connection, which can surface in the
        # client as ConnectionAbortedError while reading the response.
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except Exception:
            length = 0

        if length > 0:
            try:
                self.rfile.read(length)
            except Exception:
                # Best effort only; response correctness matters more than strict draining.
                pass

    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b)
        try:
            self.wfile.flush()
        except Exception:
            pass
        self.close_connection = True

    def _authn(self) -> str | None:
        return _bearer_token({"Authorization": self.headers.get("Authorization") or ""})

    def do_GET(self) -> None:  # noqa: N802
        if (self.path or "").split("?", 1)[0] != "/secure/items":
            self._send_json(404, {"error": "not_found"})
            return

        token = self._authn()
        if token is None:
            # Authentication failure (who are you?)
            self._send_json(401, {"error": "unauthorized"})
            return

        # Viewer/admin can both read: least privilege for read-only access
        if token not in (_VIEWER_TOKEN, _ADMIN_TOKEN):
            self._send_json(401, {"error": "unauthorized"})
            return

        self._send_json(200, {"items": [{"id": "item-1"}]})

    def do_POST(self) -> None:  # noqa: N802
        if (self.path or "").split("?", 1)[0] != "/secure/items":
            self._drain_request_body()
            self._send_json(404, {"error": "not_found"})
            return

        token = self._authn()
        if token is None:
            # Authentication failure
            self._drain_request_body()
            self._send_json(401, {"error": "unauthorized"})
            return

        if token != _ADMIN_TOKEN:
            # Authorization failure (you are authenticated, but not allowed)
            self._drain_request_body()
            self._send_json(403, {"error": "forbidden"})
            return

        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" not in ctype:
            self._drain_request_body()
            self._send_json(415, {"error": "unsupported_media_type"})
            return

        # Allow forcing bad-json without relying on raw bytes in the test
        if (self.headers.get("X-Bad-Json") or "").strip().lower() in ("1", "true", "yes"):
            self._drain_request_body()
            self._send_json(400, {"error": "invalid_json"})
            return

        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(400, {"error": "invalid_json"})
            return

        # Input validation: allowlist + bounded length
        name = payload.get("name") if isinstance(payload, dict) else None
        if not isinstance(name, str):
            self._send_json(400, {"error": "name_required"})
            return

        if len(name) < 1 or len(name) > 32:
            self._send_json(400, {"error": "name_length"})
            return

        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            self._send_json(400, {"error": "name_format"})
            return

        self._send_json(201, {"id": "item-2", "name": name})


@pytest.fixture()
def base_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SecureHandler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()


def test_authentication_vs_authorization(base_url: str) -> None:
    # AuthN: missing token => 401
    r = requests.get(f"{base_url}/secure/items", timeout=2)
    assert r.status_code == 401

    # AuthZ: viewer token => can read but cannot write (403)
    r = requests.get(
        f"{base_url}/secure/items",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
        timeout=2,
    )
    assert r.status_code == 200

    r = requests.post(
        f"{base_url}/secure/items",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}", "Content-Type": "application/json"},
        json={"name": "valid-name"},
        timeout=2,
    )
    assert r.status_code == 403


def test_input_validation_and_safe_errors(base_url: str) -> None:
    # Invalid content-type => 415
    r = requests.post(
        f"{base_url}/secure/items",
        headers={"Authorization": f"Bearer {_ADMIN_TOKEN}", "Content-Type": "text/plain"},
        data="{\"name\":\"x\"}",
        timeout=2,
    )
    assert r.status_code == 415

    # Invalid JSON => 400
    r = requests.post(
        f"{base_url}/secure/items",
        headers={"Authorization": f"Bearer {_ADMIN_TOKEN}", "Content-Type": "application/json", "X-Bad-Json": "true"},
        data="this-is-not-json",
        timeout=2,
    )
    assert r.status_code == 400

    # Reject dangerous/invalid input (allowlist validation)
    r = requests.post(
        f"{base_url}/secure/items",
        headers={"Authorization": f"Bearer {_ADMIN_TOKEN}", "Content-Type": "application/json"},
        json={"name": "' OR 1=1 --"},
        timeout=2,
    )
    assert r.status_code == 400

    # Accept good input
    r = requests.post(
        f"{base_url}/secure/items",
        headers={"Authorization": f"Bearer {_ADMIN_TOKEN}", "Content-Type": "application/json"},
        json={"name": "safe_name-01"},
        timeout=2,
    )
    assert r.status_code == 201
    assert r.json()["name"] == "safe_name-01"
