from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest

from regression.api_contract import run_contract_checks


_SECRET = "demo-scope-jwt-secret-32bytes-minimum-OK"
_ALG = "HS256"


def _make_token(*, scope: str, exp: float) -> str:
    payload = {
        "sub": "demo-user",
        "scope": scope,
        "iat": int(time.time()),
        "exp": int(exp),
        "iss": "demo-issuer",
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


def _has_scope(scope_str: str, required: str) -> bool:
    scopes = {s for s in (scope_str or "").split() if s}
    if required in scopes:
        return True
    # Simple wildcard support for the demo
    prefix = required.split(".")[0] + "."
    return any(s.endswith(".*") and s.startswith(prefix) for s in scopes) or ("*" in scopes)


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _require_token(self) -> dict | None:
        auth = (self.headers.get("Authorization") or "").strip()
        if not auth.startswith("Bearer "):
            self._send_json(401, {"error": "unauthorized", "message": "missing_bearer"})
            return None

        token = auth[len("Bearer ") :].strip()
        try:
            return jwt.decode(token, _SECRET, algorithms=[_ALG], options={"require": ["exp"]})
        except jwt.ExpiredSignatureError:
            self._send_json(401, {"error": "token_expired"})
            return None
        except Exception:
            self._send_json(401, {"error": "invalid_token"})
            return None

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        claims = self._require_token()
        if claims is None:
            return

        scope = str(claims.get("scope") or "")

        # Admin endpoints require an admin scope
        if path.startswith("/admin/") and not _has_scope(scope, "admin"):
            self._send_json(403, {"error": "insufficient_scope", "required": "admin"})
            return

        if path == "/metrics/device.model" or path == "/admin/metrics/device.model":
            if not _has_scope(scope, "metrics.read.basic"):
                self._send_json(403, {"error": "insufficient_scope", "required": "metrics.read.basic"})
                return
            self._send_json(200, {"value": "eyeSight-DEMO"})
            return

        if path == "/metrics/coverage.vendor_model_count":
            if not _has_scope(scope, "metrics.read.coverage"):
                self._send_json(403, {"error": "insufficient_scope", "required": "metrics.read.coverage"})
                return
            self._send_json(200, {"value": 42})
            return

        self._send_json(404, {"error": "not_found", "path": path})


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


def test_scope_authz_contract(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    now = time.time()

    viewer_token = _make_token(scope="metrics.read.basic", exp=now + 120)
    admin_token = _make_token(scope="metrics.read.* admin", exp=now + 120)
    expired_token = _make_token(scope="metrics.read.basic", exp=now - 120)

    invalid_token = jwt.encode(
        {"sub": "demo-user", "scope": "metrics.read.basic", "exp": int(now + 120)},
        "wrong-scope-secret-32bytes-minimum-OK",
        algorithm=_ALG,
    )

    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("SCOPE_VIEWER_TOKEN", viewer_token)
    monkeypatch.setenv("SCOPE_ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("SCOPE_EXPIRED_TOKEN", expired_token)
    monkeypatch.setenv("SCOPE_INVALID_TOKEN", invalid_token)

    results = run_contract_checks("api_checks/demo_scope_authz_contract.yaml")
    assert [r.status_code for r in results] == [200, 403, 403, 200, 401, 401]
