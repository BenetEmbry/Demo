from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


class Handler(BaseHTTPRequestHandler):
    metrics: dict[str, object] = {
        "capabilities.asset_inventory.realtime": True,
        "capabilities.monitoring.technique_count": 30,
        "network.discovery.supports_ipv6": True,
        "capabilities.device_cloud.enabled": True,
        "capabilities.classification.includes_os_version": True,
        "coverage.os_version_count": 1900,
        "coverage.vendor_model_count": 7700,
        "capabilities.asset_search_filter.enabled": True,
        "device.model": "eyeSight-DEMO",
    }

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        # Supported:
        #   GET /metrics/<metric>  -> {"value": ...}
        #   GET /healthz          -> {"ok": true}
        path = (self.path or "").split("?", 1)[0]

        if path == "/healthz":
            self._send_json(200, {"ok": True})
            return

        if path.startswith("/metrics/"):
            metric = unquote(path[len("/metrics/") :])
            if metric in self.metrics:
                self._send_json(200, {"value": self.metrics[metric]})
            else:
                self._send_json(404, {"error": "unknown_metric", "metric": metric})
            return

        self._send_json(404, {"error": "not_found", "path": path})


def main() -> int:
    parser = argparse.ArgumentParser(description="Local demo API for per-metric mode")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock API listening on http://{args.host}:{args.port}")
    print("Example: GET /metrics/device.model")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
