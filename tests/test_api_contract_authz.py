from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest

from regression.api_contract import run_contract_checks


_SECRET = "demo-jwt-secret-32bytes-minimum-OK"
_ALG = "HS256"


def _make_token(*, roles: list[str], perms: list[str], exp: float) -> str:
    payload = {
        "sub": "demo-user",
        "roles": roles,
        "perms": perms,
        "iat": int(time.time()),
        "exp": int(exp),
        "iss": "demo-issuer",
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: object) -> None:
        b = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _require_token(self) -> tuple[dict, str] | None:
        auth = (self.headers.get("Authorization") or "").strip()
        if not auth.startswith("Bearer "):
            self._send_json(401, {"error": "unauthorized", "message": "missing_bearer"})
            return None

        token = auth[len("Bearer ") :].strip()
        try:
            claims = jwt.decode(token, _SECRET, algorithms=[_ALG], options={"require": ["exp"]})
            return claims, token
        except jwt.ExpiredSignatureError:
            self._send_json(401, {"error": "token_expired"})
            return None
        except Exception:
            self._send_json(401, {"error": "invalid_token"})
            return None

    @staticmethod
    def _has_any_perm(perms: list[str], required: str) -> bool:
        return required in perms or "metrics:read:*" in perms or "*" in perms

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        authz = self._require_token()
        if authz is None:
            return
        claims, _token = authz

        roles = claims.get("roles") or []
        perms = claims.get("perms") or []
        if not isinstance(roles, list):
            roles = []
        if not isinstance(perms, list):
            perms = []

        # Role-based access: /admin/* requires admin role
        if path.startswith("/admin/") and "admin" not in roles:
            self._send_json(403, {"error": "forbidden", "message": "missing_role: admin"})
            return

        if path == "/metrics/device.model" or path == "/admin/metrics/device.model":
            if not self._has_any_perm(perms, "metrics:read:basic"):
                self._send_json(403, {"error": "forbidden", "message": "missing_permission: metrics:read:basic"})
                return
            self._send_json(200, {"value": "eyeSight-DEMO"})
            return

        if path == "/metrics/coverage.vendor_model_count":
            if not self._has_any_perm(perms, "metrics:read:coverage"):
                self._send_json(403, {"error": "forbidden", "message": "missing_permission: metrics:read:coverage"})
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


def test_authz_contract(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    now = time.time()

    viewer_token = _make_token(roles=["viewer"], perms=["metrics:read:basic"], exp=now + 120)
    admin_token = _make_token(roles=["admin"], perms=["metrics:read:*"], exp=now + 120)
    expired_token = _make_token(roles=["viewer"], perms=["metrics:read:basic"], exp=now - 120)

    invalid_token = jwt.encode(
        {"sub": "demo-user", "exp": int(now + 120)},
        "wrong-secret-32bytes-minimum-OK----",
        algorithm=_ALG,
    )

    monkeypatch.setenv("SUT_BASE_URL", base_url)
    monkeypatch.setenv("VIEWER_TOKEN", viewer_token)
    monkeypatch.setenv("ADMIN_TOKEN", admin_token)
    monkeypatch.setenv("EXPIRED_TOKEN", expired_token)
    monkeypatch.setenv("INVALID_TOKEN", invalid_token)

    results = run_contract_checks("api_checks/demo_authz_contract.yaml")
    assert [r.status_code for r in results] == [200, 403, 403, 200, 401, 401]
