#!/usr/bin/env python3
"""Smoke-test a running PDS4 Viewer (container, Codespace, or production).

  python scripts/smoke_test.py http://localhost:8000
  python scripts/smoke_test.py https://viewer.example.gov --label array_2d_image/thermal_neutron_map.xml

Checks: UI served, API healthy, a label opens from the "local" source, an image renders,
a table page reads, and paths outside the configured root are rejected. When the source
isn't the bundled test_data, pass --label (relative to the source root) and --kind.
Standard library only; exits non-zero on the first failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def call(base: str, method: str, path: str, params: dict | None = None, body: dict | None = None):
    url = base.rstrip("/") + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail and not ok else ''}")
    if not ok:
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_url")
    ap.add_argument("--source", default="local")
    ap.add_argument("--label", default="array_2d_image/thermal_neutron_map.xml")
    ap.add_argument("--table-label", default="table_character_cal/ch3_cht_cal_20230825T15_362682724_v1.xml")
    ap.add_argument("--skip-ui", action="store_true", help="API-only deployment (no bundled frontend)")
    a = ap.parse_args()
    b = a.base_url

    if not a.skip_ui:
        status, ctype, body = call(b, "GET", "/")
        check("UI is served", status == 200 and b"<div id=\"root\"" in body, f"HTTP {status}")

    status, _, body = call(b, "GET", "/api/health")
    check("API health", status == 200 and json.loads(body).get("status") == "ok", f"HTTP {status}")

    status, _, body = call(b, "GET", "/api/browse/sources")
    sources = {s["name"]: s["root"] for s in json.loads(body)} if status == 200 else {}
    check(f"source '{a.source}' configured", a.source in sources, f"available: {list(sources)}")
    root = sources[a.source]

    status, _, _ = call(b, "GET", "/api/browse/list", {"source": a.source, "path": "/etc"})
    check("paths outside the root are rejected", status == 404, f"HTTP {status}")

    def open_label(rel: str) -> dict:
        path = root.rstrip("/") + "/" + rel
        status, _, body = call(b, "POST", "/api/browse/open", {"source": a.source, "path": path})
        check(f"open {rel}", status == 200, f"HTTP {status} {body[:200]!r}")
        return json.loads(body)

    image = open_label(a.label)
    arr = next((s for s in image["structures"] if "Array" in s["structure_type"]), None)
    check("label has an array structure", arr is not None)
    lid, idx = image["label_id"], arr["index"]
    status, ctype, body = call(b, "POST", f"/api/images/{lid}/{idx}/render", body={"colormap": "viridis"})
    check("image renders as PNG", status == 200 and body[:4] == b"\x89PNG", f"HTTP {status}")
    status, _, body = call(b, "GET", f"/api/images/{lid}/{idx}/statistics")
    check("image statistics", status == 200 and "max" in json.loads(body), f"HTTP {status}")

    if a.table_label:
        table = open_label(a.table_label)
        tbl = next((s for s in table["structures"] if "Table" in s["structure_type"]), None)
        check("label has a table structure", tbl is not None)
        status, _, body = call(b, "GET", f"/api/tables/{table['label_id']}/{tbl['index']}/data", {"limit": 5})
        rows = json.loads(body).get("data", []) if status == 200 else []
        check("table page reads", status == 200 and len(rows) == min(5, tbl["record_count"] or 5), f"HTTP {status}")

    print("All smoke checks passed.")


if __name__ == "__main__":
    main()
