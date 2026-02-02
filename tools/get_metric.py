from __future__ import annotations

import argparse
import json

from regression.sut import load_sut_adapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a single metric using the configured SUT adapter")
    parser.add_argument("metric", help="Metric key (e.g. device.model)")
    args = parser.parse_args()

    sut = load_sut_adapter()
    value = sut.get_metric(args.metric)

    try:
        print(json.dumps(value, indent=2, sort_keys=True))
    except TypeError:
        print(str(value))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
