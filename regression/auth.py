from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests


@dataclass
class OAuth2Token:
    access_token: str
    token_type: str = "Bearer"
    expires_at: float | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # 10s skew
        return time.time() >= (self.expires_at - 10)


@dataclass
class AuthConfig:
    mode: str  # none|api_key|oauth2

    # API key
    api_key: str | None = None
    api_key_header: str = "X-API-Key"
    api_key_query_param: str | None = None

    # OAuth2 (Bearer)
    bearer_token: str | None = None

    # OAuth2 client credentials
    oauth2_token_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    oauth2_scope: str | None = None

    _lock: threading.Lock | None = None
    _cached_token: OAuth2Token | None = None

    def _get_lock(self) -> threading.Lock:
        if self._lock is None:
            self._lock = threading.Lock()
        return self._lock

    def apply_headers(self, headers: dict[str, str]) -> dict[str, str]:
        headers = dict(headers)

        if self.mode == "api_key":
            if self.api_key and self.api_key_header:
                headers[self.api_key_header] = self.api_key
            return headers

        if self.mode == "oauth2":
            token = self.get_bearer_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            return headers

        return headers

    def apply_url(self, url: str) -> str:
        if self.mode != "api_key":
            return url
        if not self.api_key or not self.api_key_query_param:
            return url

        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        q[self.api_key_query_param] = self.api_key
        return urlunparse(p._replace(query=urlencode(q)))

    def get_bearer_token(self) -> str | None:
        # Static token wins.
        if self.bearer_token:
            return self.bearer_token

        # Client-credentials token.
        if not self.oauth2_token_url:
            return None

        with self._get_lock():
            if self._cached_token and not self._cached_token.is_expired():
                return self._cached_token.access_token

            token = _fetch_client_credentials_token(
                token_url=self.oauth2_token_url,
                client_id=self.oauth2_client_id,
                client_secret=self.oauth2_client_secret,
                scope=self.oauth2_scope,
            )
            self._cached_token = token
            return token.access_token


def load_auth_config_from_env() -> AuthConfig:
    mode = (os.getenv("SUT_AUTH_MODE") or "none").strip().lower()

    if mode in ("", "none"):
        return AuthConfig(mode="none")

    if mode in ("api_key", "apikey"):
        api_key = (os.getenv("SUT_API_KEY") or "").strip() or None
        api_key_header = (os.getenv("SUT_API_KEY_HEADER") or "X-API-Key").strip() or "X-API-Key"
        api_key_query_param = (os.getenv("SUT_API_KEY_QUERY_PARAM") or "").strip() or None
        return AuthConfig(
            mode="api_key",
            api_key=api_key,
            api_key_header=api_key_header,
            api_key_query_param=api_key_query_param,
        )

    if mode in ("oauth2", "bearer"):
        bearer_token = (os.getenv("SUT_OAUTH_TOKEN") or "").strip() or None
        token_url = (os.getenv("SUT_OAUTH_TOKEN_URL") or "").strip() or None
        client_id = (os.getenv("SUT_OAUTH_CLIENT_ID") or "").strip() or None
        client_secret = (os.getenv("SUT_OAUTH_CLIENT_SECRET") or "").strip() or None
        scope = (os.getenv("SUT_OAUTH_SCOPE") or "").strip() or None

        return AuthConfig(
            mode="oauth2",
            bearer_token=bearer_token,
            oauth2_token_url=token_url,
            oauth2_client_id=client_id,
            oauth2_client_secret=client_secret,
            oauth2_scope=scope,
        )

    raise RuntimeError(f"Unsupported SUT_AUTH_MODE: {mode!r}")


def _fetch_client_credentials_token(
    *,
    token_url: str,
    client_id: str | None,
    client_secret: str | None,
    scope: str | None,
) -> OAuth2Token:
    if not client_id or not client_secret:
        raise RuntimeError("SUT_OAUTH_CLIENT_ID and SUT_OAUTH_CLIENT_SECRET are required for client-credentials")

    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    headers["Authorization"] = f"Basic {basic}"

    data = {"grant_type": "client_credentials"}
    if scope:
        data["scope"] = scope

    timeout_s = float(os.getenv("SUT_TIMEOUT_S") or "10")
    verify_raw = (os.getenv("SUT_VERIFY_TLS") or "true").strip().lower()
    verify_tls = verify_raw not in ("0", "false", "no")

    resp = requests.post(token_url, data=data, headers=headers, timeout=timeout_s, verify=verify_tls)
    resp.raise_for_status()

    payload: Any = resp.json() if resp.content else {}
    if not isinstance(payload, dict):
        raise RuntimeError("OAuth2 token endpoint returned non-object JSON")

    access_token = str(payload.get("access_token") or "").strip()
    token_type = str(payload.get("token_type") or "Bearer").strip() or "Bearer"
    expires_in = payload.get("expires_in")

    if not access_token:
        raise RuntimeError("OAuth2 token endpoint response missing access_token")

    expires_at = None
    if expires_in is not None:
        try:
            expires_at = time.time() + float(expires_in)
        except Exception:
            expires_at = None

    return OAuth2Token(access_token=access_token, token_type=token_type, expires_at=expires_at)
