from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from regression.api_contract import run_contract_checks


class _State:
    created_count = 0


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: object, *, extra_headers: dict[str, str] | None = None) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Request-Id", str(uuid.uuid4()))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _require_auth(self) -> bool:
        auth = (self.headers.get("Authorization") or "").strip()
        return auth == "Bearer demo-rest-token"

    def do_GET(self) -> None:  # noqa: N802
        path, _, query = (self.path or "").partition("?")

        if path.startswith("/items") and not self._require_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        if path == "/items":
            qs = parse_qs(query)
            page = int((qs.get("page") or ["1"])[0])
            limit = int((qs.get("limit") or ["2"])[0])

            total = 5
            start = (page - 1) * limit
            end = min(start + limit, total)
            items = [{"id": f"item-{i+1}"} for i in range(start, end)]

            next_page = page + 1 if end < total else None
            headers = {}
            if next_page is not None:
                headers["Link"] = f"<{self._base_url()}/items?page={next_page}&limit={limit}>; rel=\"next\""

            self._send_json(
                200,
                {"items": items, "page": page, "limit": limit, "total": total, "next_page": next_page},
                extra_headers=headers,
            )
            return

        if path.startswith("/items/"):
            # Not found for demo
            self._send_json(404, {"error": "not_found"})
            return

        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if (self.path or "").split("?", 1)[0] != "/items":
            self._send_json(404, {"error": "not_found"})
            return

        if not self._require_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        # Trigger a bad-json path if header present (simplifies testing 400).
        if (self.headers.get("X-Bad-Json") or "").strip().lower() in ("1", "true", "yes"):
            self._send_json(400, {"error": "invalid_json"})
            return

        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" not in ctype:
            self._send_json(415, {"error": "unsupported_media_type"})
            return

        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        try:
            _ = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(400, {"error": "invalid_json"})
            return

        _State.created_count += 1
        # Reuse metric_value schema: {"value": ...}
        self._send_json(201, {"value": f"created-{_State.created_count}"})

    def do_PATCH(self) -> None:  # noqa: N802
        if (self.path or "").split("?", 1)[0] == "/items":
            if not self._require_auth():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(405, {"error": "method_not_allowed"})
            return
        self._send_json(404, {"error": "not_found"})

    def _base_url(self) -> str:
        host = self.headers.get("Host") or "127.0.0.1"
        return f"http://{host}"


@pytest.fixture()
def base_url() -> str:
    _State.created_count = 0

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()


def test_rest_concepts_contract(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("REST_TOKEN", "demo-rest-token")

    results = run_contract_checks("api_checks/demo_rest_contract.yaml")
    assert [r.status_code for r in results] == [401, 200, 201, 405, 404, 400]
