# Requirements schema (datasheet regression)

This repo stores datasheet-derived requirements as YAML and turns them into executable regression tests.

## File format

`requirements/*.yaml`

Top-level:

```yaml
requirements:
  - id: DS-001
    title: "<short human name>"
    source:
      document: "eyeSight Datasheet"
      file: "eyeSight Datasheet.pdf"
      page: 3
      excerpt: "...text snippet from PDF..."

    # What are we asserting?
    type: one_of
    metric: "device.model"          # key to query from your SUT adapter

    # Expected values depend on type
    expected:
      any_of: ["X", "Y"]

    # Optional metadata
    tags: ["hardware", "datasheet"]
    notes: "How this is verified"
```

## Supported `type`

- `presence`: metric exists / returns non-empty
  - expected: *(none)*
- `equals`: exact match
  - expected: `{ value: <scalar> }`
- `one_of`: membership
  - expected: `{ any_of: [<scalar>, ...] }`
- `range`: numeric range (inclusive)
  - expected: `{ min: <number>, max: <number> }` (either can be omitted)
- `regex`: string matches pattern
  - expected: `{ pattern: "..." }`

## `metric` naming

Use dotted keys that map naturally to your SUT adapter, e.g.

- `device.model`
- `device.firmware_version`
- `network.supported_protocols`
- `performance.max_throughput_mbps`

Your adapter is implemented in `regression/sut.py`.

## API adapter configuration

The default implementation supports an HTTP API adapter via environment variables:

- `SUT_MODE=api`
- `SUT_BASE_URL=https://your-sut.example`

Optional:

- `SUT_TOKEN` (Bearer token)
- `SUT_TIMEOUT_S` (default `10`)
- `SUT_VERIFY_TLS` (`true`/`false`, default `true`)
- `SUT_METRICS_ENDPOINT` (default `/metrics`) where the API returns a JSON mapping (or `{ "metrics": { ... } }`)
- `SUT_METRIC_URL_TEMPLATE` (if set, tests will call this per metric)
  - Example: `{base_url}/metrics/{metric}` (expects `{ "value": ... }` or raw JSON)
- `SUT_METRIC_VALUE_PATH` (optional) dotted path for nested per-metric JSON
  - Example: `data.value` for `{ "data": { "value": 123 } }`
