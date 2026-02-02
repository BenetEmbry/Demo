# Datasheet regression suite

This repo turns requirements from `eyeSight Datasheet.pdf` into an executable regression test suite.

## Quick start (generate + share results)

Generate a shareable report bundle (JSON + HTML dashboard):

- PowerShell:
	- `$env:REPORT_DIR='reports'`
	- `pytest`

Share with the team:

- Publish the `reports/` folder to an internal file share or static web server
- Share the link to `index.html` (inside that folder)

Local preview:

- `python tools/serve_reports.py --dir reports --port 8001`
- Open `http://127.0.0.1:8001/`

## Setup

From the repo root:

- Install deps: `pip install -r requirements-dev.txt`

## CI/CD

GitHub Actions runs the suite on every push/PR via `.github/workflows/python-tests.yml`.

For demo sharing, use `REPORT_DIR` to produce a static report bundle (`index.html` + JSON artifacts) that can be published to any internal static host.

## Extract candidate requirements from the PDF

- `python tools/extract_datasheet_requirements.py --pdf "eyeSight Datasheet.pdf"`

Outputs:

- `requirements/eyesight_text_by_page.txt` (raw extracted text)
- `requirements/eyesight_candidates.yaml` (heuristic candidate lines)

Review `requirements/eyesight_candidates.yaml`, then promote the ones you care about into:

- `requirements/eyesight_datasheet.yaml`

Schema docs:

- `requirements/requirements_schema.md`

## Run the regression suite

- `pytest`

By default, the suite is green until you add requirements.

### Demo run (no API wiring)

This runs the same harness end-to-end using the built-in `dict` adapter and a demo requirements file.

- `$env:SUT_MODE='dict'`
- `$env:SUT_METRICS_JSON='{"device.model":"eyeSight-DEMO","device.firmware_version":"1.0.0","performance.max_throughput_mbps":250}'`
- `$env:REQ_FILE='requirements/eyesight_demo.yaml'`
- `pytest`

Once you add requirements, implement the System Under Test (SUT) adapter:

- `regression/sut.py::load_sut_adapter()` (already includes an API adapter)

That function must return an object with:

- `get_metric(metric: str) -> Any`

### API mode (recommended)

Set:

- `SUT_MODE=api`
- `SUT_BASE_URL=https://your-sut.example`

Optional:

- `SUT_TOKEN` (legacy bearer token; kept for backward compatibility)
- `SUT_AUTH_MODE` (`none`|`api_key`|`oauth2`)
	- API key:
		- `SUT_API_KEY`
		- `SUT_API_KEY_HEADER` (default `X-API-Key`) or `SUT_API_KEY_QUERY_PARAM`
	- OAuth2:
		- Static token: `SUT_OAUTH_TOKEN`
		- Client credentials: `SUT_OAUTH_TOKEN_URL`, `SUT_OAUTH_CLIENT_ID`, `SUT_OAUTH_CLIENT_SECRET`, optional `SUT_OAUTH_SCOPE`
- `SUT_METRICS_ENDPOINT` (default `/metrics`) for a bulk JSON mapping
- `SUT_METRIC_URL_TEMPLATE` for per-metric fetches, e.g. `{base_url}/metrics/{metric}`
- `SUT_METRIC_VALUE_PATH` for nested JSON, e.g. `data.value`

Example (PowerShell):

- `$env:SUT_MODE='api'`
- `$env:SUT_BASE_URL='https://your-sut.example'`
- `$env:SUT_METRIC_URL_TEMPLATE='{base_url}/metrics/{metric}'`
- `$env:SUT_METRIC_VALUE_PATH='data.value'`  # only if needed
- `# API key example`
- `$env:SUT_AUTH_MODE='api_key'`
- `$env:SUT_API_KEY='your-key'`
- `# OAuth2 static token example`
- `$env:SUT_AUTH_MODE='oauth2'`
- `$env:SUT_OAUTH_TOKEN='your-bearer-token'`
- `pytest`

Quick metric sanity check:

- `python tools/get_metric.py device.model`

### API reporting

When `SUT_MODE=api`, every HTTP call made by the adapter is recorded (URL, status code, latency, error).

- Console summary: automatically shown at the end of `pytest` if any API calls happened
- JSON report file: set `API_REPORT_PATH=api_report.json` before running `pytest`

"Everything" reporting (single folder bundle):

- Set `REPORT_DIR=reports` and run `pytest`
	- Writes `reports/api_report.json` (API call telemetry)
	- Writes `reports/evidence.json` (evidence manifest with hashes)
	- Writes `reports/run_report.json` (consolidated run summary pointing to the above)
	- Writes `reports/index.html` (static dashboard; open directly or serve over HTTP)

If you prefer an explicit path:

- Set `RUN_REPORT_PATH=run_report.json`

### Share results with the team (internal website link)

Best option: host the `REPORT_DIR` folder on an internal static site or file server.

- Generate reports: set `REPORT_DIR=reports` then run `pytest`
- Publish `reports/` somewhere your team can reach (SMB share, internal web server, CI artifact hosting)
- Share the link to `index.html`

Local preview (for demos):

- `python tools/serve_reports.py --dir reports --port 8001`
- Open `http://127.0.0.1:8001/`

Optional grouping by API name:

- Set `API_LABEL_RULES` as `Label=regex;Other=regex2` (regex matches full URL)
	- Example: `Metrics=/metrics/;Health=/healthz`

Standalone endpoint status check (useful for health endpoints):

- `python tools/api_status_report.py --base-url https://your-sut.example --paths /healthz,/readyz`

## API contract testing (status/schema/logic)

Python contract runner uses:

- status codes
- JSON schema validation
- business logic/data accuracy assertions
- positive and negative cases

Demo contract spec:

- `api_checks/demo_contract.yaml`

OAuth2 demo contract spec (shows `auth: oauth2` and `auth: none` overrides):

- `api_checks/demo_oauth2_contract.yaml`

Authn/Authz demo contract spec (token validation, RBAC, permission boundaries, expired tokens):

- `api_checks/demo_authz_contract.yaml`

Scope-based Authz demo contract spec (OAuth2-style `scope` claim enforcing permission boundaries):

- `api_checks/demo_scope_authz_contract.yaml`

Cloud-native contract spec (health/readiness/liveness/version):

- `api_checks/demo_cloud_native_contract.yaml`

REST concepts contract spec (methods/status/auth/json/pagination/errors):

- `api_checks/demo_rest_contract.yaml`

Run against the demo mock API:

- Terminal 1: `python tools/mock_api.py --port 8000`
- Terminal 2:
	- `python -c "from regression.api_contract import run_contract_checks; run_contract_checks('api_checks/demo_contract.yaml', base_url='http://127.0.0.1:8000')"`

Run OAuth2 contract checks (example with client-credentials token endpoint):

- `$env:SUT_BASE_URL='https://your-sut.example'`
- `$env:SUT_AUTH_MODE='oauth2'`
- `$env:SUT_OAUTH_TOKEN_URL='https://your-sut.example/oauth/token'`
- `$env:SUT_OAUTH_CLIENT_ID='...'`
- `$env:SUT_OAUTH_CLIENT_SECRET='...'`
- `python -c "from regression.api_contract import run_contract_checks; run_contract_checks('api_checks/demo_oauth2_contract.yaml')"`

Run Authn/Authz contract checks (tokens injected via env vars):

- `$env:SUT_BASE_URL='https://your-sut.example'`
- `$env:VIEWER_TOKEN='...'`
- `$env:ADMIN_TOKEN='...'`
- `$env:EXPIRED_TOKEN='...'`
- `$env:INVALID_TOKEN='...'`
- `python -c "from regression.api_contract import run_contract_checks; run_contract_checks('api_checks/demo_authz_contract.yaml')"`

Run scope-based Authz contract checks:

- `$env:SUT_BASE_URL='https://your-sut.example'`
- `$env:SCOPE_VIEWER_TOKEN='...'`
- `$env:SCOPE_ADMIN_TOKEN='...'`
- `$env:SCOPE_EXPIRED_TOKEN='...'`
- `$env:SCOPE_INVALID_TOKEN='...'`
- `python -c "from regression.api_contract import run_contract_checks; run_contract_checks('api_checks/demo_scope_authz_contract.yaml')"`

Run cloud-native contract checks:

- `$env:SUT_BASE_URL='https://your-sut.example'`
- `python -c "from regression.api_contract import run_contract_checks; run_contract_checks('api_checks/demo_cloud_native_contract.yaml')"`

Run REST contract checks:

- `$env:SUT_BASE_URL='https://your-sut.example'`
- `$env:REST_TOKEN='...'`
- `python -c "from regression.api_contract import run_contract_checks; run_contract_checks('api_checks/demo_rest_contract.yaml')"`

## Backend DB validation (optional)

If you need to validate backend DB state, there is an optional hook (skipped unless configured):

- Set `DB_MODE=sqlite`
- Set `DB_SQLITE_PATH=...`
- Create `DB_CHECKS_FILE` YAML with queries

The test is in `tests/test_db_validation_optional.py`.

### SQL basics / indexes / transactions

There are demo tests that cover common SQL fundamentals using SQLite:

- SQL basics (tables, `SELECT COUNT(*)`, `JOIN`)
- Index existence checks
- Transactions (commit, rollback, atomicity)

See:

- `tests/test_sqlite_db_checks_demo.py` (uses the existing `DB_MODE=sqlite` hook)
- `tests/test_sql_transactions.py`

### When to use SQL vs NoSQL (rule of thumb)

- Use **SQL** when you need strong consistency, joins/relational integrity, complex querying, and transactional guarantees (e.g., orders/billing, inventory, audit trails).
- Use **NoSQL** when you need flexible schemas, very high write throughput, horizontal scaling, or document/key-value access patterns (e.g., telemetry, caching, content documents).
- Many cloud-native systems use both: SQL for system-of-record + NoSQL/cache for performance.

### Local harness mode (no API)

- `$env:SUT_MODE='dict'`
- `$env:SUT_METRICS_JSON='{"device.model":"X"}'`

Example metrics:

- `device.model`
- `device.firmware_version`
- `network.supported_protocols`

## Compliance (SOC2 / ISO-style)

This repo includes demo-focused checks to help you validate and produce traceable test evidence for common compliance controls.

- **Access auditing / logging validation**: see tests under `tests/test_compliance_*.py` (demo mock APIs emit audit events + request IDs).
- **Data masking**: API reports automatically redact sensitive query parameters (e.g., API keys) before writing JSON artifacts.
- **Encryption verification**: there are tests that validate TLS verification behavior (self-signed cert fails when `SUT_VERIFY_TLS=true`).
- **Traceable evidence**: optionally write an evidence manifest with hashes of artifacts.

Evidence artifact output:

- Set `API_REPORT_PATH=artifacts/api_report.json`
- Set `EVIDENCE_PATH=artifacts/evidence.json`
- Run `pytest`

The evidence manifest records SHA-256 hashes of artifacts so you can prove what was produced by a specific run, without embedding secrets.

Optional masking controls:

- `SENSITIVE_QUERY_PARAMS=param1,param2` to force-redact additional query parameter values in API report artifacts.

## Networking fundamentals (cloud-native friendly)

This repo includes small, local-only tests that cover common networking concepts often needed for troubleshooting APIs and cloud-native systems:

- **TCP vs UDP**: TCP is connection-oriented; UDP is datagram-based (connectionless). See `tests/test_network_tcp_udp.py`.
- **HTTP vs HTTPS**: HTTPS is HTTP over TLS (encryption + server identity verification). TLS verification behavior is tested in `tests/test_compliance_tls_encryption.py`.
- **Ports**: Services listen on ports (e.g., 80/443). The tests show open vs closed port behavior (`ECONNREFUSED`). See `tests/test_network_ports_dns_firewall.py`.
- **DNS**: Resolves names (e.g., `localhost`) into IPs. See `tests/test_network_ports_dns_firewall.py`.
- **Firewalls**: Often either reject (fast failure / refused) or drop (timeouts). The tests simulate both. See `tests/test_network_ports_dns_firewall.py`.
- **Network traffic concepts**: request IDs, latency, rate limits, retries.
	- Request IDs + rate limiting: `tests/test_cloud_native.py`
	- Latency/status reporting: enabled automatically via the API reporting summary

## Secure coding practices

This suite includes executable tests that demonstrate core secure-coding concepts:

- **Input validation**: strict JSON parsing, content-type checks, and allowlist validation.
	- See `tests/test_secure_coding_practices.py`
- **Authentication vs authorization**: `401 Unauthorized` (missing/invalid identity) vs `403 Forbidden` (authenticated but not permitted).
	- See `tests/test_secure_coding_practices.py`, plus the contract-based AuthZ demos: `api_checks/demo_authz_contract.yaml`, `api_checks/demo_scope_authz_contract.yaml`
- **Data encryption in transit**: TLS verification (fail closed by default).
	- See `tests/test_compliance_tls_encryption.py` and set `SUT_VERIFY_TLS=true|false`
- **Data encryption at rest** (demo-friendly): optional encrypted copies of test artifacts.
	- Set `ARTIFACT_ENCRYPTION_KEY` (Fernet key) and the suite will also write `*.enc` copies for `API_REPORT_PATH` and `EVIDENCE_PATH` outputs.
	- Demonstrated by `tests/test_data_encryption_at_rest_demo.py`
- **Least privilege**: prefer read-only tokens/scopes for read endpoints and require elevated scopes only where needed.
	- See `tests/test_secure_coding_practices.py` and `tests/test_api_contract_scope_authz.py`
