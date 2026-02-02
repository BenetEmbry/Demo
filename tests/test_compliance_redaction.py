from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from regression.api_reporting import write_api_report
from regression.sut import load_sut_adapter


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        b = b'{"value": "eyeSight-DEMO"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


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


def test_api_report_redacts_query_params(monkeypatch: pytest.MonkeyPatch, tmp_path, base_url: str) -> None:
    # Force API key into query string to validate we don't leak it in evidence artifacts.
    monkeypatch.setenv("SUT_MODE", "api")
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("SUT_METRIC_URL_TEMPLATE", "{base_url}/metrics/{metric}")

    monkeypatch.setenv("SUT_AUTH_MODE", "api_key")
    monkeypatch.setenv("SUT_API_KEY", "supersecret")
    monkeypatch.setenv("SUT_API_KEY_QUERY_PARAM", "api_key")

    sut = load_sut_adapter()
    assert sut.get_metric("device.model") == "eyeSight-DEMO"

    report_path = tmp_path / "api_report.json"
    write_api_report(str(report_path))

    data = json.loads(report_path.read_text(encoding="utf-8"))
    text = json.dumps(data)

    assert "supersecret" not in text
    assert "api_key=REDACTED" in text
