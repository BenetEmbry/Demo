from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from regression.redaction import redact_text


@dataclass(frozen=True)
class GitInfo:
    head: str | None
    branch: str | None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def get_git_info(repo_root: str | Path) -> GitInfo:
    root = Path(repo_root)
    git_dir = root / ".git"
    head_txt = _read_text(git_dir / "HEAD")
    if not head_txt:
        return GitInfo(head=None, branch=None)

    if head_txt.startswith("ref:"):
        ref = head_txt.split(":", 1)[1].strip()
        branch = ref.split("/", 2)[-1] if ref.startswith("refs/heads/") else None
        ref_txt = _read_text(git_dir / ref)
        if ref_txt:
            return GitInfo(head=ref_txt, branch=branch)

        # Packed refs fallback
        packed = _read_text(git_dir / "packed-refs")
        if packed:
            for line in packed.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                if " " not in line:
                    continue
                sha, name = line.split(" ", 1)
                if name.strip() == ref:
                    return GitInfo(head=sha.strip(), branch=branch)

        return GitInfo(head=None, branch=branch)

    # Detached HEAD
    return GitInfo(head=head_txt, branch=None)


def sha256_file(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_evidence_bundle(
    path: str | Path,
    *,
    api_report_path: str | None = None,
    extra_artifacts: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> str:
    """Write a small evidence manifest for SOC2/ISO-style traceability.

    The manifest is designed to be safe to share (no tokens/credentials). It records hashes
    of artifacts so you can prove what was produced by a test run.
    """

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    repo_root = Path(repo_root) if repo_root is not None else Path.cwd()
    git = get_git_info(repo_root)

    artifacts: list[dict[str, Any]] = []

    def _add_artifact(p: str) -> None:
        try:
            ap = Path(p)
            if not ap.exists() or not ap.is_file():
                return
            artifacts.append(
                {
                    "path": str(ap.as_posix()),
                    "sha256": sha256_file(ap),
                    "bytes": ap.stat().st_size,
                }
            )
        except Exception:
            return

    if api_report_path:
        _add_artifact(api_report_path)

    for a in extra_artifacts or []:
        _add_artifact(a)

    manifest = {
        "run_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": {"head": git.head, "branch": git.branch},
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
        },
        "config": {
            "sut_base_url": redact_text(os.getenv("SUT_BASE_URL") or "") or None,
            "sut_auth_mode": (os.getenv("SUT_AUTH_MODE") or "none").strip() or "none",
            "sut_verify_tls": (os.getenv("SUT_VERIFY_TLS") or "true").strip(),
        },
        "artifacts": artifacts,
    }

    # Final safety pass: redact bearer/basic patterns anywhere in the JSON string.
    text = json.dumps(manifest, indent=2, sort_keys=False)
    text = redact_text(text)

    out_path.write_text(text, encoding="utf-8")
    return str(out_path)
