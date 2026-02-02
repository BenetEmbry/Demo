from __future__ import annotations

from pathlib import Path

from regression.html_report import write_html_report


def test_write_html_report_creates_index(tmp_path: Path) -> None:
    rr = tmp_path / "run_report.json"
    rr.write_text('{"pytest":{"exitstatus":0,"counts":{"passed":1,"failed":0}}}', encoding="utf-8")

    # If README.md exists next to index.html, the report should link to it.
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    out = tmp_path / "index.html"
    p = write_html_report(out, run_report_path=str(rr), api_report_path=None, evidence_path=None)

    assert p
    text = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in text.lower()
    assert "run_report.json" in text
    assert "README.md" in text
