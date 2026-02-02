from __future__ import annotations

import argparse
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="Serve a report folder (static HTML + JSON artifacts).")
    p.add_argument("--dir", default=os.getenv("REPORT_DIR") or "reports", help="Report directory to serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args()

    root = Path(args.dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    os.chdir(root)
    httpd = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
    print(f"Serving {root} on http://{args.host}:{args.port}/ (Ctrl+C to stop)")
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
