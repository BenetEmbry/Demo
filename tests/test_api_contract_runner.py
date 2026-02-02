from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

import pytest

from regression.api_contract import run_contract_checks


class _Handler(BaseHTTPRequestHandler):
    metrics: dict[str, object] = {
        "device.model": "eyeSight-DEMO",
    }

    def _send_json(self, status: int, payload: str) -> None:
        b = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        if path == "/healthz":
            self._send_json(200, '{"ok": true}')
            return

        if path.startswith("/metrics/"):
            metric = unquote(path[len("/metrics/") :])
            if metric in self.metrics:
                self._send_json(200, '{"value": "eyeSight-DEMO"}')
            else:
                self._send_json(404, '{"error": "unknown_metric", "metric": "' + metric + '"}')
            return

        self._send_json(404, '{"error": "not_found"}')


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


def test_demo_contract_file(mock_api_base_url: str) -> None:
    # Use the repo's demo contract file, but point it at the in-process server.
    run_contract_checks("api_checks/demo_contract.yaml", base_url=mock_api_base_url)
