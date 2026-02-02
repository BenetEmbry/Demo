from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from regression.sut import load_sut_adapter


class _Handler(BaseHTTPRequestHandler):
    token_calls = 0
    last_token = ""

    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self) -> None:  # noqa: N802
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

        type(self).token_calls += 1
        tok = f"tok-{type(self).token_calls}"
        type(self).last_token = tok

        # expires_in=0 makes the token immediately expired (with our 10s skew)
        self._send_json(200, {"access_token": tok, "token_type": "Bearer", "expires_in": 0})

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        if path != "/metrics/device.model":
            self._send_json(404, {"error": "not_found"})
            return

        expected_auth = f"Bearer {type(self).last_token}" if type(self).last_token else None
        if expected_auth is None or self.headers.get("Authorization") != expected_auth:
            self._send_json(401, {"error": "unauthorized"})
            return

        self._send_json(200, {"value": "eyeSight-DEMO"})


@pytest.fixture()
def base_url() -> str:
    _Handler.token_calls = 0
    _Handler.last_token = ""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()


def test_oauth2_refreshes_expired_token(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("SUT_METRIC_URL_TEMPLATE", "{base_url}/metrics/{metric}")

    monkeypatch.setenv("SUT_AUTH_MODE", "oauth2")
    monkeypatch.setenv("SUT_OAUTH_TOKEN_URL", f"{base_url}/oauth/token")
    monkeypatch.setenv("SUT_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("SUT_OAUTH_CLIENT_SECRET", "secret")

    sut = load_sut_adapter()
    assert sut.get_metric("device.model") == "eyeSight-DEMO"
    assert sut.get_metric("device.model") == "eyeSight-DEMO"

    assert _Handler.token_calls == 2
