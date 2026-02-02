from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from regression.evidence import get_git_info, sha256_file
from regression.redaction import redact_text


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str
    bytes: int


def _artifact_ref(path: str | None) -> ArtifactRef | None:
    if not path:
        return None

    p = Path(path)
    if not p.exists() or not p.is_file():
        return None

    return ArtifactRef(path=str(p.as_posix()), sha256=sha256_file(p), bytes=p.stat().st_size)


def _try_read_json(path: str | None) -> Any | None:
    if not path:
        return None

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def write_run_report(
    path: str | Path,
    *,
    exitstatus: int,
    duration_s: float | None,
    test_counts: dict[str, int],
    failed_nodeids: list[str],
    api_report_path: str | None,
    evidence_path: str | None,
    repo_root: str | Path | None = None,
) -> str:
    """Write a consolidated run report that points to all artifacts.

    This is meant as a single file you can hand to a stakeholder:
    - what ran (git/runtime)
    - what happened (pytest summary)
    - what was produced (artifact hashes)
    - safe to share (redaction pass)
    """

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    repo_root = Path(repo_root) if repo_root is not None else Path.cwd()
    git = get_git_info(repo_root)

    api_ref = _artifact_ref(api_report_path)
    evidence_ref = _artifact_ref(evidence_path)

    api_summary = None
    api_json = _try_read_json(api_report_path)
    if isinstance(api_json, dict):
        api_summary = api_json.get("summary")

    evidence_json = _try_read_json(evidence_path)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": {"head": git.head, "branch": git.branch},
        "pytest": {
            "exitstatus": exitstatus,
            "duration_s": duration_s,
            "counts": test_counts,
            "failed": failed_nodeids[:50],
        },
        "artifacts": {
            "api_report": api_ref.__dict__ if api_ref else None,
            "evidence": evidence_ref.__dict__ if evidence_ref else None,
        },
        "api": {
            "summary": api_summary,
        },
        "evidence": evidence_json if isinstance(evidence_json, dict) else None,
    }

    text = json.dumps(report, indent=2, sort_keys=False)
    text = redact_text(text)

    out_path.write_text(text, encoding="utf-8")
    return str(out_path)
