from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from regression.auth import load_auth_config_from_env


class SutAdapter(Protocol):
    def get_metric(self, metric: str) -> Any:
        """Return the current value for a metric key (e.g., 'device.model')."""


@dataclass(frozen=True)
class DictSutAdapter:
    """Small adapter useful for local testing of the test harness itself."""

    metrics: dict[str, Any]

    def get_metric(self, metric: str) -> Any:
        return self.metrics.get(metric)


@dataclass
class ApiSutAdapter:
    base_url: str
    token: str | None = None
    timeout_s: float = 10.0
    verify_tls: bool = True
    metrics_endpoint: str = "/metrics"
    metric_url_template: str | None = None
    metric_value_path: str | None = None
    auth_mode: str | None = None

    _session: requests.Session | None = None
    _cache: dict[str, Any] | None = None
    _auth = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}

        # Back-compat: old SUT_TOKEN env var (Bearer)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        auth = self._get_auth()
        return auth.apply_headers(headers)

    def _get_auth(self):
        if self._auth is None:
            self._auth = load_auth_config_from_env()
        return self._auth

    def _get_json(self, url: str) -> Any:
        # Apply API-key query parameter if configured.
        url = self._get_auth().apply_url(url)

        start = time.perf_counter()
        status_code: int | None = None
        ok = False
        error: str | None = None

        try:
            resp = self._get_session().get(
                url,
                headers=self._headers(),
                timeout=self.timeout_s,
                verify=self.verify_tls,
            )
            status_code = resp.status_code
            ok = bool(resp.ok)
            resp.raise_for_status()
            # Some APIs send JSON with a text content-type; be tolerant.
            return resp.json()
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            try:
                from regression.api_reporting import record_api_call

                record_api_call(
                    method="GET",
                    url=url,
                    status_code=status_code,
                    ok=ok,
                    elapsed_ms=elapsed_ms,
                    error=error,
                )
            except Exception:
                # Never let reporting break the SUT adapter.
                pass

    def _fetch_all_metrics(self) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + self.metrics_endpoint
        payload = self._get_json(url)

        # Accept either {"metrics": {...}} or a raw mapping {...}
        if isinstance(payload, dict) and "metrics" in payload and isinstance(payload["metrics"], dict):
            return payload["metrics"]
        if isinstance(payload, dict):
            return payload

        raise RuntimeError(
            "API metrics endpoint returned unsupported JSON shape; expected an object/mapping."
        )

    @staticmethod
    def _extract_by_path(payload: Any, dotted_path: str) -> Any:
        cur: Any = payload
        for part in dotted_path.split("."):
            if not isinstance(cur, dict):
                return None
            if part not in cur:
                return None
            cur = cur[part]
        return cur

    def _extract_metric_value(self, payload: Any) -> Any:
        if self.metric_value_path:
            extracted = self._extract_by_path(payload, self.metric_value_path)
            if extracted is not None:
                return extracted

        # Default: accept either {"value": ...} or raw scalar
        if isinstance(payload, dict) and "value" in payload:
            return payload.get("value")

        # Common alternative shapes
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict) and "value" in payload["data"]:
            return payload["data"].get("value")
        if isinstance(payload, dict) and "result" in payload:
            return payload.get("result")

        return payload

    def get_metric(self, metric: str) -> Any:
        metric = str(metric)

        if self.metric_url_template:
            url = self.metric_url_template.format(base_url=self.base_url.rstrip("/"), metric=metric)
            payload = self._get_json(url)
            return self._extract_metric_value(payload)

        if self._cache is None:
            self._cache = self._fetch_all_metrics()
        return self._cache.get(metric)


def load_sut_adapter() -> SutAdapter:
    """Entry point used by tests.

    Configure via environment variables:

    - SUT_MODE: "api" or "dict"

        API mode:
        - SUT_BASE_URL: e.g. https://sut.example.local
        - SUT_TOKEN: optional bearer token
        - SUT_AUTH_MODE: optional (none|api_key|oauth2)
            - api_key: set SUT_API_KEY and optionally SUT_API_KEY_HEADER / SUT_API_KEY_QUERY_PARAM
            - oauth2: set SUT_OAUTH_TOKEN (static) OR SUT_OAUTH_TOKEN_URL + client credentials
        - SUT_TIMEOUT_S: optional (default 10)
        - SUT_VERIFY_TLS: optional true/false (default true)
        - SUT_METRICS_ENDPOINT: optional path for bulk metrics (default /metrics)
        - SUT_METRIC_URL_TEMPLATE: optional template for per-metric GETs
            Example: "{base_url}/metrics/{metric}" or "{base_url}/metric?name={metric}"
        - SUT_METRIC_VALUE_PATH: optional dotted path to extract value from per-metric JSON
            Example: "data.value" for {"data": {"value": 123}}

    Dict mode (for harness validation):
    - SUT_METRICS_JSON: JSON object mapping metric -> value
    """

    mode = (os.getenv("SUT_MODE") or "").strip().lower()

    if mode in ("", "none"):
        raise RuntimeError(
            "No SUT adapter configured. Set SUT_MODE=api and SUT_BASE_URL to run against your API, "
            "or SUT_MODE=dict with SUT_METRICS_JSON for local testing."
        )

    if mode == "dict":
        raw = os.getenv("SUT_METRICS_JSON") or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError("SUT_METRICS_JSON must be valid JSON") from e
        if not isinstance(data, dict):
            raise RuntimeError("SUT_METRICS_JSON must be a JSON object")
        return DictSutAdapter(metrics=data)

    if mode == "api":
        base_url = (os.getenv("SUT_BASE_URL") or "").strip()
        if not base_url:
            raise RuntimeError("SUT_BASE_URL is required when SUT_MODE=api")

        token = (os.getenv("SUT_TOKEN") or "").strip() or None
        timeout_s = float(os.getenv("SUT_TIMEOUT_S") or "10")

        verify_raw = (os.getenv("SUT_VERIFY_TLS") or "true").strip().lower()
        verify_tls = verify_raw not in ("0", "false", "no")

        metrics_endpoint = (os.getenv("SUT_METRICS_ENDPOINT") or "/metrics").strip()
        metric_url_template = (os.getenv("SUT_METRIC_URL_TEMPLATE") or "").strip() or None
        metric_value_path = (os.getenv("SUT_METRIC_VALUE_PATH") or "").strip() or None

        return ApiSutAdapter(
            base_url=base_url,
            token=token,
            timeout_s=timeout_s,
            verify_tls=verify_tls,
            metrics_endpoint=metrics_endpoint,
            metric_url_template=metric_url_template,
            metric_value_path=metric_value_path,
        )

    raise RuntimeError(f"Unsupported SUT_MODE: {mode!r}")
