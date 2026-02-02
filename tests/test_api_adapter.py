from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest

from regression.sut import load_sut_adapter


class _Handler(BaseHTTPRequestHandler):
    metrics: dict[str, object] = {
        "device.model": "eyeSight-DEMO",
        "coverage.vendor_model_count": 7700,
    }

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]

        if path.startswith("/metrics/"):
            metric = unquote(path[len("/metrics/") :])
            if metric in self.metrics:
                self._send_json(200, {"value": self.metrics[metric]})
            else:
                self._send_json(404, {"error": "unknown_metric"})
            return

        self._send_json(404, {"error": "not_found"})


@pytest.fixture()
def mock_api_base_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()


def test_api_per_metric_template(monkeypatch: pytest.MonkeyPatch, mock_api_base_url: str) -> None:
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", mock_api_base_url)
    monkeypatch.setenv("SUT_METRIC_URL_TEMPLATE", "{base_url}/metrics/{metric}")

    sut = load_sut_adapter()

    assert sut.get_metric("device.model") == "eyeSight-DEMO"
    assert sut.get_metric("coverage.vendor_model_count") == 7700
