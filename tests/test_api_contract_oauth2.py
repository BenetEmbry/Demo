from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from regression.api_contract import run_contract_checks


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self) -> None:  # noqa: N802
        # OAuth2 token endpoint
        path = (self.path or "").split("?", 1)[0]
        if path != "/oauth/token":
            self._send_json(404, {"error": "not_found"})
            return

        expected = "Basic " + base64.b64encode(b"client:secret").decode("ascii")
        if (self.headers.get("Authorization") or "") != expected:
            self._send_json(401, {"error": "invalid_client"})
            return

        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        if (form.get("grant_type") or [""])[0] != "client_credentials":
            self._send_json(400, {"error": "unsupported_grant_type"})
            return

        self._send_json(200, {"access_token": "demo-token", "token_type": "Bearer", "expires_in": 3600})

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        if path != "/metrics/device.model":
            self._send_json(404, {"error": "not_found"})
            return

        if self.headers.get("Authorization") != "Bearer demo-token":
            self._send_json(401, {"error": "unauthorized"})
            return

        self._send_json(200, {"value": "eyeSight-DEMO"})


@pytest.fixture()
def base_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()


def test_contract_runner_oauth2_overrides(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("SUT_AUTH_MODE", "oauth2")
    monkeypatch.setenv("SUT_OAUTH_TOKEN_URL", f"{base_url}/oauth/token")
    monkeypatch.setenv("SUT_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("SUT_OAUTH_CLIENT_SECRET", "secret")

    results = run_contract_checks("api_checks/demo_oauth2_contract.yaml")
    assert [r.status_code for r in results] == [200, 401]
