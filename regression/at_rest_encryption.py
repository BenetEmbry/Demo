from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Final

from cryptography.fernet import Fernet, InvalidToken


_KEY_ENV_VAR: Final[str] = "ARTIFACT_ENCRYPTION_KEY"


def _looks_like_hex(s: str) -> bool:
    if len(s) != 64:
        return False
    try:
        bytes.fromhex(s)
        return True
    except Exception:
        return False


def _load_fernet_key_from_env(env_var: str = _KEY_ENV_VAR) -> bytes | None:
    raw = (os.getenv(env_var) or "").strip()
    if not raw:
        return None

    # Accept either a normal Fernet key (base64 urlsafe) or a 32-byte hex key.
    if _looks_like_hex(raw):
        key_bytes = bytes.fromhex(raw)
        return base64.urlsafe_b64encode(key_bytes)

    return raw.encode("utf-8")


def get_fernet(env_var: str = _KEY_ENV_VAR) -> Fernet | None:
    key = _load_fernet_key_from_env(env_var)
    if not key:
        return None

    try:
        return Fernet(key)
    except Exception as e:  # pragma: no cover
        raise ValueError(f"Invalid Fernet key in env var {env_var!r}") from e


def encrypt_bytes(plaintext: bytes, *, env_var: str = _KEY_ENV_VAR) -> bytes:
    f = get_fernet(env_var)
    if not f:
        raise RuntimeError(f"Missing encryption key (set {env_var})")
    return f.encrypt(plaintext)


def decrypt_bytes(ciphertext: bytes, *, env_var: str = _KEY_ENV_VAR) -> bytes:
    f = get_fernet(env_var)
    if not f:
        raise RuntimeError(f"Missing encryption key (set {env_var})")

    try:
        return f.decrypt(ciphertext)
    except InvalidToken as e:
        raise ValueError("Invalid ciphertext or wrong key") from e


def write_encrypted_copy_if_configured(
    plaintext_path: str | Path,
    *,
    out_path: str | Path | None = None,
    env_var: str = _KEY_ENV_VAR,
) -> str | None:
    """Optionally write an encrypted copy of an on-disk artifact.

    If the key env var is unset, this is a no-op.

    Returns the encrypted path if written, else None.
    """

    f = get_fernet(env_var)
    if not f:
        return None

    p = Path(plaintext_path)
    if not p.exists() or not p.is_file():
        return None

    out = Path(out_path) if out_path is not None else p.with_suffix(p.suffix + ".enc")
    out.parent.mkdir(parents=True, exist_ok=True)

    ciphertext = f.encrypt(p.read_bytes())
    out.write_bytes(ciphertext)
    return str(out)
