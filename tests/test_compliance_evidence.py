from __future__ import annotations

import json

import pytest

from regression.api_reporting import record_api_call, write_api_report
from regression.evidence import sha256_file, write_evidence_bundle


def test_evidence_bundle_contains_hashes_and_no_secrets(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate a call that would have had a sensitive query param.
    record_api_call(
        method="GET",
        url="http://example.local/metrics/device.model?api_key=supersecret",
        status_code=200,
        ok=True,
        elapsed_ms=1.2,
        error=None,
    )

    api_report = tmp_path / "api_report.json"
    write_api_report(str(api_report))

    evidence_path = tmp_path / "evidence.json"
    monkeypatch.setenv("SUT_BASE_URL", "http://example.local")

    write_evidence_bundle(str(evidence_path), api_report_path=str(api_report), repo_root=tmp_path)

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert "run_id" in evidence
    assert evidence["artifacts"], "Expected at least one artifact"

    artifact = evidence["artifacts"][0]
    assert artifact["path"].endswith("api_report.json")
    assert artifact["sha256"] == sha256_file(api_report)

    # Safety: no secrets in evidence.
    text = evidence_path.read_text(encoding="utf-8")
    assert "supersecret" not in text
    assert "Bearer " not in text
