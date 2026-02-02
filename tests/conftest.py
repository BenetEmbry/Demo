from __future__ import annotations

import os
import time
from pathlib import Path
import shutil


_RUN_START_TIME: float | None = None
_TEST_COUNTS = {
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "xfailed": 0,
    "xpassed": 0,
    "error": 0,
}
_FAILED_NODEIDS: list[str] = []


def pytest_sessionstart(session):  # noqa: ANN001
    global _RUN_START_TIME
    _RUN_START_TIME = time.time()


def pytest_runtest_logreport(report):  # noqa: ANN001
    # Count only the actual test call outcome (not setup/teardown).
    if getattr(report, "when", None) != "call":
        return

    outcome = getattr(report, "outcome", None)
    if outcome == "passed":
        if getattr(report, "wasxfail", False):
            _TEST_COUNTS["xpassed"] += 1
        else:
            _TEST_COUNTS["passed"] += 1
        return

    if outcome == "failed":
        if getattr(report, "wasxfail", False):
            _TEST_COUNTS["xfailed"] += 1
        else:
            _TEST_COUNTS["failed"] += 1
            nodeid = getattr(report, "nodeid", None)
            if isinstance(nodeid, str) and nodeid:
                _FAILED_NODEIDS.append(nodeid)
        return

    if outcome == "skipped":
        _TEST_COUNTS["skipped"] += 1
        return


def _resolve_report_paths() -> tuple[str | None, str | None, str | None]:
    """Resolve (api_report_path, evidence_path, run_report_path)."""

    report_dir = (os.getenv("REPORT_DIR") or "").strip()
    api_path = (os.getenv("API_REPORT_PATH") or "").strip()
    evidence_path = (os.getenv("EVIDENCE_PATH") or "").strip()
    run_report_path = (os.getenv("RUN_REPORT_PATH") or "").strip()

    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
        if not api_path:
            api_path = os.path.join(report_dir, "api_report.json")
        if not evidence_path:
            evidence_path = os.path.join(report_dir, "evidence.json")
        if not run_report_path:
            run_report_path = os.path.join(report_dir, "run_report.json")

    return (api_path or None, evidence_path or None, run_report_path or None)


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    api_path, evidence_path, run_report_path = _resolve_report_paths()
    from regression.at_rest_encryption import write_encrypted_copy_if_configured

    # If we're producing a shareable report bundle, include README.md in the bundle
    # so teammates can download/view the usage instructions alongside the results.
    report_dir = (os.getenv("REPORT_DIR") or "").strip()
    if report_dir:
        try:
            src = Path.cwd() / "README.md"
            dst = Path(report_dir) / "README.md"
            if src.exists() and src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                write_encrypted_copy_if_configured(str(dst))
        except Exception:
            # Never break test runs for report bundling
            pass

    # Evidence can be produced independently.
    evidence_out: str | None = None
    if evidence_path:
        from regression.evidence import write_evidence_bundle

        evidence_out = write_evidence_bundle(evidence_path, api_report_path=api_path)
        write_encrypted_copy_if_configured(evidence_out)

    # API report is only meaningful if API calls occurred, but it's useful to always emit
    # a file in demo runs when REPORT_DIR is set.
    api_out: str | None = None
    if api_path:
        from regression.api_reporting import write_api_report

        api_out = write_api_report(api_path)
        write_encrypted_copy_if_configured(api_out)

    if run_report_path:
        from regression.run_report import write_run_report

        duration_s = None
        if _RUN_START_TIME is not None:
            duration_s = max(0.0, time.time() - _RUN_START_TIME)

        rr = write_run_report(
            run_report_path,
            exitstatus=int(exitstatus),
            duration_s=duration_s,
            test_counts=dict(_TEST_COUNTS),
            failed_nodeids=list(_FAILED_NODEIDS),
            api_report_path=api_out,
            evidence_path=evidence_out,
        )
        write_encrypted_copy_if_configured(rr)

        # Optional: also produce a static HTML dashboard next to the JSON artifacts.
        # Enabled when REPORT_DIR is set (recommended) OR when RUN_REPORT_HTML_PATH is set.
        report_dir = (os.getenv("REPORT_DIR") or "").strip()
        html_path = (os.getenv("RUN_REPORT_HTML_PATH") or "").strip()
        if report_dir and not html_path:
            html_path = os.path.join(report_dir, "index.html")

        if html_path:
            from regression.html_report import write_html_report

            out_html = write_html_report(
                html_path,
                run_report_path=rr,
                api_report_path=api_out,
                evidence_path=evidence_out,
            )
            write_encrypted_copy_if_configured(out_html)


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ANN001
    # Print a short status summary if there were any API calls.
    try:
        from regression.api_reporting import get_api_calls, summarize_calls

        calls = get_api_calls()
        if not calls:
            return

        summary = summarize_calls(calls)
        terminalreporter.write_line("\nAPI status report (from HTTP calls):")
        terminalreporter.write_line(
            f"  total_calls={summary['total_calls']} total_errors={summary['total_errors']}"
        )

        labels = summary.get("labels") or []
        if labels:
            terminalreporter.write_line("  by_label:")
            for l in labels[:10]:
                terminalreporter.write_line(
                    f"    {l['label']} count={l['count']} errors={l['error_count']} status_codes={l['status_codes']}"
                )

        for ep in summary["endpoints"][:10]:
            terminalreporter.write_line(
                f"  {ep['method']} {ep['url']} count={ep['count']} errors={ep['error_count']} "
                f"p95_ms={ep['p95_ms']}"
            )
    except Exception:
        # Never break pytest output
        return
