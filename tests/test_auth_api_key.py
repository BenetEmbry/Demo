from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest
import requests

from regression.sut import load_sut_adapter


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:  # noqa: N802
        api_key = self.headers.get("X-API-Key")
        if api_key != "demo-key":
            self._send_json(401, {"error": "unauthorized"})
            return

        path = (self.path or "").split("?", 1)[0]
        if path.startswith("/metrics/"):
            metric = unquote(path[len("/metrics/") :])
            if metric == "device.model":
                self._send_json(200, {"value": "eyeSight-DEMO"})
                return
            self._send_json(404, {"error": "unknown_metric"})
            return

        self._send_json(404, {"error": "not_found"})


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


def test_api_key_positive(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("SUT_METRIC_URL_TEMPLATE", "{base_url}/metrics/{metric}")
    monkeypatch.setenv("SUT_AUTH_MODE", "api_key")
    monkeypatch.setenv("SUT_API_KEY", "demo-key")

    sut = load_sut_adapter()
    assert sut.get_metric("device.model") == "eyeSight-DEMO"


def test_api_key_negative(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("SUT_METRIC_URL_TEMPLATE", "{base_url}/metrics/{metric}")
    monkeypatch.setenv("SUT_AUTH_MODE", "api_key")
    monkeypatch.setenv("SUT_API_KEY", "wrong")

    sut = load_sut_adapter()
    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        sut.get_metric("device.model")
    assert excinfo.value.response is not None
    assert excinfo.value.response.status_code == 401
