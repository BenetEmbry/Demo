from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from regression.redaction import redact_text


def _try_read_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_html_report(
    out_path: str | Path,
    *,
    run_report_path: str | None,
    api_report_path: str | None,
    evidence_path: str | None,
    title: str = "Test Run Report",
) -> str:
    """Write a static HTML report that can be hosted anywhere.

    It is designed to work as a simple "drop-in" artifact:
    - open locally from disk, OR
    - serve from an internal static site / file share / web server.
    """

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    run_json = _try_read_json(run_report_path)
    api_json = _try_read_json(api_report_path)
    evidence_json = _try_read_json(evidence_path)

    generated_at = datetime.now(timezone.utc).isoformat()

    def _dumps(obj: Any) -> str:
        return json.dumps(obj, indent=2, sort_keys=False)

    payload = {
        "generated_at": generated_at,
        "run": run_json,
        "api": api_json,
        "evidence": evidence_json,
        "links": {
            "run_report": Path(run_report_path).name if run_report_path else None,
            "api_report": Path(api_report_path).name if api_report_path else None,
            "evidence": Path(evidence_path).name if evidence_path else None,
          "readme": "README.md" if (out.parent / "README.md").exists() else None,
        },
    }

    # Redact anything that might have slipped in.
    embedded = redact_text(_dumps(payload))

    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0b1220;
      --card: #0f1a2e;
      --text: #e6edf3;
      --muted: #93a4b8;
      --ok: #2ea043;
      --bad: #f85149;
      --warn: #d29922;
      --link: #58a6ff;
      --border: rgba(255,255,255,0.08);
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;
    }}

    body {{
      margin: 0;
      background: radial-gradient(1200px 900px at 15% -20%, rgba(88,166,255,0.22), transparent 45%),
                  radial-gradient(900px 700px at 85% 0%, rgba(46,160,67,0.18), transparent 40%),
                  var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }}

    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .header {{ display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 22px; }}
    .meta {{ color: var(--muted); font-size: 13px; }}

    .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; margin-top: 16px; }}
    .card {{ grid-column: span 12; background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }}
    .row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .pill {{ display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); font-size: 13px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--muted); }}
    .dot.ok {{ background: var(--ok); }}
    .dot.bad {{ background: var(--bad); }}
    .dot.warn {{ background: var(--warn); }}

    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    pre {{
      margin: 0;
      padding: 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: rgba(0,0,0,0.25);
      overflow: auto;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.45;
    }}

    .split {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    @media (min-width: 900px) {{
      .split {{ grid-template-columns: 1fr 1fr; }}
    }}

    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"header\">
      <h1>{title}</h1>
      <div class=\"meta\">Generated: <span id=\"generatedAt\"></span></div>
    </div>

    <div class=\"grid\">
      <div class=\"card\">
        <div class=\"row\" id=\"summaryPills\"></div>
        <div class=\"row\" style=\"margin-top:10px\" id=\"links\"></div>
      </div>

      <div class=\"card\">
        <div class=\"split\">
          <div>
            <div class=\"muted\" style=\"margin-bottom:8px\">Pytest summary</div>
            <pre id=\"pytestSummary\"></pre>
          </div>
          <div>
            <div class=\"muted\" style=\"margin-bottom:8px\">API summary</div>
            <pre id=\"apiSummary\"></pre>
          </div>
        </div>
      </div>

      <div class=\"card\">
        <div class=\"muted\" style=\"margin-bottom:8px\">Consolidated JSON (redacted)</div>
        <pre id=\"raw\"></pre>
      </div>
    </div>
  </div>

<script>
  const DATA = {embedded};

  function pill(label, value, kind) {{
    const el = document.createElement('div');
    el.className = 'pill';
    const dot = document.createElement('span');
    dot.className = 'dot ' + (kind || '');
    const t = document.createElement('span');
    t.textContent = label + ': ' + value;
    el.appendChild(dot);
    el.appendChild(t);
    return el;
  }}

  document.getElementById('generatedAt').textContent = DATA.generated_at || '';

  const run = DATA.run || {{}};
  const pytest = (run.pytest || {{}});
  const counts = (pytest.counts || {{}});
  const failed = (pytest.failed || []);

  const passed = counts.passed || 0;
  const failedCount = counts.failed || 0;
  const skipped = counts.skipped || 0;

  const statusKind = failedCount > 0 ? 'bad' : 'ok';

  const pills = document.getElementById('summaryPills');
  pills.appendChild(pill('Status', failedCount > 0 ? 'FAIL' : 'PASS', statusKind));
  pills.appendChild(pill('Passed', passed, 'ok'));
  pills.appendChild(pill('Failed', failedCount, failedCount > 0 ? 'bad' : 'ok'));
  pills.appendChild(pill('Skipped', skipped, skipped > 0 ? 'warn' : 'ok'));

  const apiSummary = (DATA.api && DATA.api.summary) ? DATA.api.summary : (DATA.run && DATA.run.api && DATA.run.api.summary);
  if (apiSummary && typeof apiSummary === 'object') {{
    pills.appendChild(pill('API calls', apiSummary.total_calls ?? 'n/a', ''));
    pills.appendChild(pill('API errors', apiSummary.total_errors ?? 'n/a', (apiSummary.total_errors || 0) > 0 ? 'warn' : 'ok'));
  }}

  const links = document.getElementById('links');
  const linkList = [
    ['run_report.json', DATA.links && DATA.links.run_report],
    ['api_report.json', DATA.links && DATA.links.api_report],
    ['evidence.json', DATA.links && DATA.links.evidence],
    ['README.md', DATA.links && DATA.links.readme],
  ];
  for (const [label, href] of linkList) {{
    if (!href) continue;
    const a = document.createElement('a');
    a.href = href;
    a.textContent = 'Open ' + label;
    a.className = 'pill';
    links.appendChild(a);
  }}

  const pytestText = {{
    exitstatus: pytest.exitstatus,
    duration_s: pytest.duration_s,
    counts,
    failed: failed.slice(0, 20),
  }};

  document.getElementById('pytestSummary').textContent = JSON.stringify(pytestText, null, 2);
  document.getElementById('apiSummary').textContent = JSON.stringify(apiSummary || {{note: 'No API report available'}}, null, 2);
  document.getElementById('raw').textContent = JSON.stringify(DATA, null, 2);
</script>
</body>
</html>"""

    out.write_text(html, encoding="utf-8")
    return str(out)
