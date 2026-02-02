from __future__ import annotations

import json

from regression.run_report import write_run_report


def test_write_run_report_includes_artifact_hashes(tmp_path) -> None:
    api_report = tmp_path / "api_report.json"
    api_report.write_text(json.dumps({"summary": {"total_calls": 1, "total_errors": 0}}), encoding="utf-8")

    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"run_id": "r1", "config": {"sut_base_url": "REDACTED"}}), encoding="utf-8")

    out = tmp_path / "run_report.json"
    p = write_run_report(
        out,
        exitstatus=0,
        duration_s=1.23,
        test_counts={"passed": 1, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "error": 0},
        failed_nodeids=[],
        api_report_path=str(api_report),
        evidence_path=str(evidence),
    )

    data = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert p
    assert data["pytest"]["exitstatus"] == 0
    assert data["api"]["summary"]["total_calls"] == 1
    assert data["artifacts"]["api_report"]["sha256"]
    assert data["artifacts"]["evidence"]["sha256"]
