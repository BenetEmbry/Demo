from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
import yaml

from regression.auth import AuthConfig, load_auth_config_from_env
from regression.schema_validation import validate_schema


@dataclass(frozen=True)
class HttpResult:
    url: str
    status_code: int
    json: Any


_ENV_VAR_PATTERN = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|(?P<bare>[A-Za-z_][A-Za-z0-9_]*))|%(?P<windows>[A-Za-z_][A-Za-z0-9_]*)%")


def _expand_env_vars(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value

    def _replace(m: re.Match[str]) -> str:
        name = m.group("braced") or m.group("bare") or m.group("windows")
        return os.getenv(name) or ""

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _json_path_get(data: Any, dotted_path: str) -> Any:
    cur: Any = data
    for part in dotted_path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _apply_assertions(payload: Any, assertions: list[dict[str, Any]]) -> None:
    for a in assertions:
        atype = (a.get("type") or "").strip()
        path = (a.get("path") or "").strip()

        if atype == "json_path_exists":
            assert path, "json_path_exists requires 'path'"
            value = _json_path_get(payload, path)
            assert value is not None, f"Expected JSON path '{path}' to exist"
            continue

        if atype == "json_path_equals":
            assert path, "json_path_equals requires 'path'"
            expected = a.get("expected")
            actual = _json_path_get(payload, path)
            assert actual == expected, f"Expected {path} == {expected!r}, got {actual!r}"
            continue

        if atype == "json_path_one_of":
            assert path, "json_path_one_of requires 'path'"
            options = a.get("any_of")
            assert isinstance(options, list) and options, "json_path_one_of requires non-empty any_of"
            actual = _json_path_get(payload, path)
            assert actual in options, f"Expected {path} in {options!r}, got {actual!r}"
            continue

        if atype == "json_path_range":
            assert path, "json_path_range requires 'path'"
            actual = _json_path_get(payload, path)
            assert actual is not None, f"Expected JSON path '{path}' to exist"
            actual_num = float(actual)
            if "min" in a and a["min"] is not None:
                assert actual_num >= float(a["min"]), f"Expected {path} >= {a['min']}, got {actual_num}"
            if "max" in a and a["max"] is not None:
                assert actual_num <= float(a["max"]), f"Expected {path} <= {a['max']}, got {actual_num}"
            continue

        raise AssertionError(f"Unknown assertion type: {atype!r}")


def _apply_expected_headers(resp: requests.Response, expected: dict[str, Any]) -> None:
    for raw_name, rule in expected.items():
        name = str(raw_name)
        actual = resp.headers.get(name)

        # Shorthand: expected_headers: {"Content-Type": "application/json"}
        if isinstance(rule, str):
            assert actual is not None, f"Expected header '{name}' to exist"
            assert actual == rule, f"Expected header '{name}' == {rule!r}, got {actual!r}"
            continue

        if rule is True:
            assert actual is not None, f"Expected header '{name}' to exist"
            continue

        if isinstance(rule, dict):
            if rule.get("exists"):
                assert actual is not None, f"Expected header '{name}' to exist"

            if "equals" in rule:
                assert actual is not None, f"Expected header '{name}' to exist"
                expected_value = str(rule.get("equals"))
                assert actual == expected_value, f"Expected header '{name}' == {expected_value!r}, got {actual!r}"

            if "contains" in rule:
                assert actual is not None, f"Expected header '{name}' to exist"
                needle = str(rule.get("contains"))
                assert needle in actual, f"Expected header '{name}' to contain {needle!r}, got {actual!r}"

            if "regex" in rule:
                assert actual is not None, f"Expected header '{name}' to exist"
                rx = str(rule.get("regex"))
                assert re.search(rx, actual), f"Expected header '{name}' to match /{rx}/, got {actual!r}"

            continue

        raise AssertionError(f"Unsupported expected_headers rule for '{name}': {rule!r}")


def run_contract_checks(contract_file: str, *, base_url: str | None = None, token: str | None = None) -> list[HttpResult]:
    """Run contract checks described in a YAML file.

    Validates:
    - Status codes
    - Response schema (JSON Schema)
    - Business logic / data accuracy via simple assertions
    - Positive and negative cases

    Config supports env var expansion in base_url/token.
    """

    with open(contract_file, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}

    base_url = base_url or os.getenv("SUT_BASE_URL") or ""
    base_url = str(_expand_env_vars(base_url)).strip()
    if not base_url:
        raise RuntimeError("base_url is required (pass base_url= or set SUT_BASE_URL)")

    session = requests.Session()
    base_headers = {"Accept": "application/json"}

    # Back-compat: old SUT_TOKEN env var (Bearer) or explicit token=...
    token = token if token is not None else (os.getenv("SUT_TOKEN") or "")
    token = str(_expand_env_vars(token)).strip() or None
    if token:
        base_headers["Authorization"] = f"Bearer {token}"

    default_auth = load_auth_config_from_env()

    timeout_s = float(os.getenv("SUT_TIMEOUT_S") or "10")
    verify_raw = (os.getenv("SUT_VERIFY_TLS") or "true").strip().lower()
    verify_tls = verify_raw not in ("0", "false", "no")

    results: list[HttpResult] = []

    for check in spec.get("checks") or []:
        method = str(check.get("method") or "GET").upper()
        path = str(_expand_env_vars(check.get("path") or ""))
        assert path, "Each check needs a 'path'"

        url = path if path.startswith(("http://", "https://")) else urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))

        # Allow per-check auth override: none|api_key|oauth2
        auth_override = (check.get("auth") or "").strip().lower()
        if auth_override in ("", "default"):
            auth = default_auth
        elif auth_override in ("none",):
            auth = AuthConfig(mode="none")
        elif auth_override in ("api_key", "apikey"):
            auth = AuthConfig(
                mode="api_key",
                api_key=default_auth.api_key,
                api_key_header=default_auth.api_key_header,
                api_key_query_param=default_auth.api_key_query_param,
            )
        elif auth_override in ("oauth2", "bearer"):
            auth = AuthConfig(
                mode="oauth2",
                bearer_token=default_auth.bearer_token,
                oauth2_token_url=default_auth.oauth2_token_url,
                oauth2_client_id=default_auth.oauth2_client_id,
                oauth2_client_secret=default_auth.oauth2_client_secret,
                oauth2_scope=default_auth.oauth2_scope,
            )
        else:
            raise AssertionError(f"Unknown auth override: {auth_override!r}")

        url = auth.apply_url(url)

        expected_status = int(check.get("expected_status") or 200)
        schema_path = check.get("schema")
        assertions = check.get("assert") or []
        expected_headers = check.get("expected_headers") or {}
        if expected_headers and not isinstance(expected_headers, dict):
            raise AssertionError("check.expected_headers must be a mapping")

        headers = auth.apply_headers(base_headers)
        extra_headers = check.get("headers") or {}
        if not isinstance(extra_headers, dict):
            raise AssertionError("check.headers must be a mapping")
        headers.update({str(k): str(_expand_env_vars(v)) for k, v in extra_headers.items()})

        resp = session.request(method, url, headers=headers, timeout=timeout_s, verify=verify_tls)

        # Status code validation
        assert (
            resp.status_code == expected_status
        ), f"{method} {url}: expected status {expected_status}, got {resp.status_code}"

        # Response header validation (content-type, pagination, request IDs, etc)
        if expected_headers:
            _apply_expected_headers(resp, dict(expected_headers))

        # JSON parsing + schema validation
        payload = resp.json() if resp.content else None
        if schema_path:
            validate_schema(str(schema_path), payload)

        # Business logic / data accuracy assertions
        if assertions:
            assert isinstance(payload, (dict, list)), f"{method} {url}: payload not JSON object/array"
            _apply_assertions(payload, list(assertions))

        results.append(HttpResult(url=url, status_code=resp.status_code, json=payload))

    return results
