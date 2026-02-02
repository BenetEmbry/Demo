from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_DEFAULT_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "signature",
    "sig",
    "key",
    "client_secret",
    "password",
}


_BEARER_RE = re.compile(r"\bBearer\s+[^\s]+", re.IGNORECASE)
_BASIC_RE = re.compile(r"\bBasic\s+[^\s]+", re.IGNORECASE)


def _get_sensitive_query_keys() -> set[str]:
    keys = set(_DEFAULT_SENSITIVE_KEYS)

    # Include the configured API-key query param if present.
    k = (os.getenv("SUT_API_KEY_QUERY_PARAM") or "").strip().lower()
    if k:
        keys.add(k)

    extra = (os.getenv("SENSITIVE_QUERY_PARAMS") or "").strip()
    if extra:
        for part in extra.split(","):
            p = part.strip().lower()
            if p:
                keys.add(p)

    return keys


def redact_url(url: str) -> str:
    """Redact sensitive query parameter values in a URL."""

    if not url:
        return url

    sensitive = _get_sensitive_query_keys()
    parsed = urlparse(url)
    if not parsed.query:
        return url

    q = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        kl = (k or "").lower()
        if kl in sensitive or "token" in kl or "secret" in kl or (kl.endswith("key") and kl != "monkey"):
            q.append((k, "REDACTED"))
        else:
            q.append((k, v))

    return urlunparse(parsed._replace(query=urlencode(q)))


def redact_text(text: str) -> str:
    """Redact bearer/basic credentials from any free-form text."""

    if not text:
        return text

    text = _BEARER_RE.sub("Bearer REDACTED", text)
    text = _BASIC_RE.sub("Basic REDACTED", text)
    return text
