#!/usr/bin/env python3
"""Build a requirement/bug -> test -> result traceability matrix from JUnit XML reports.

Reads JUnit files from pytest (--junitxml), Vitest and Playwright. Keys are found in:
  * <property name="requirement|bug" value="REQ-04"/>   (pytest, Playwright annotations)
  * test names containing "[REQ-04]" or "@REQ-04"        (Vitest, Playwright tags)

Usage:
  python traceability/trace_matrix.py backend/test-results/junit-backend.xml \\
      frontend/test-results/junit-unit.xml frontend/test-results/junit-e2e.xml \\
      --markdown trace-matrix.md --json trace-matrix.json [--strict]

--strict exits non-zero if any requirement/bug has no test or any traced test failed.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY_RE = re.compile(r"[\[@]((?:REQ|BUG)-\d+)\]?")


def load_catalog() -> dict:
    return json.loads((HERE / "traceability.json").read_text())


def parse_reports(paths: list[Path]) -> list[dict]:
    results = []
    for path in paths:
        if not path.exists():
            print(f"warning: report not found: {path}", file=sys.stderr)
            continue
        suite_label = path.stem.replace("junit-", "")
        for case in ET.parse(path).getroot().iter("testcase"):
            name = case.get("name", "")
            keys = {p.get("value") for p in case.iter("property") if p.get("name") in ("requirement", "bug")}
            keys |= set(KEY_RE.findall(name))
            keys.discard(None)
            if case.find("failure") is not None or case.find("error") is not None:
                status = "failed"
            elif case.find("skipped") is not None:
                status = "skipped"
            else:
                status = "passed"
            results.append({
                "suite": suite_label,
                "test": f"{case.get('classname', '')}::{name}".strip(":"),
                "status": status,
                "keys": sorted(keys),
            })
    return results


def build(catalog: dict, results: list[dict]) -> dict:
    repo = catalog["repository"]
    matrix = {}
    for key, item in catalog["items"].items():
        if item["type"] not in ("requirement", "bug", "vulnerability"):
            continue
        tests = [r for r in results if key in r["keys"]]
        failed = sum(r["status"] == "failed" for r in tests)
        passed = sum(r["status"] == "passed" for r in tests)
        status = "NOT TESTED" if not tests else ("FAIL" if failed else "PASS")
        matrix[key] = {
            "title": item["title"],
            "type": item["type"],
            "issue": f"{repo}#{item['issue']}" if item.get("issue") else None,
            "status": status,
            "passed": passed,
            "failed": failed,
            "tests": tests,
        }
    unknown = sorted({k for r in results for k in r["keys"]} - set(catalog["items"]))
    return {"repository": repo, "items": matrix, "unknown_keys": unknown,
            "untraced_tests": sum(1 for r in results if not r["keys"]), "total_tests": len(results)}


def to_markdown(m: dict) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "NOT TESTED": "⚠️"}
    lines = ["## Requirements traceability", "",
             "| Key | Issue | Status | Tests (pass/total) | Title |", "|---|---|---|---|---|"]
    for key, row in m["items"].items():
        issue = row["issue"] or "—"
        lines.append(f"| {key} | {issue} | {icon[row['status']]} {row['status']} | "
                     f"{row['passed']}/{len(row['tests'])} | {row['title']} |")
    lines += ["", f"{m['total_tests']} tests in reports; {m['untraced_tests']} not tagged to a requirement or bug."]
    if m["unknown_keys"]:
        lines.append(f"Unknown keys referenced by tests: {', '.join(m['unknown_keys'])}")
    lines += ["", "<details><summary>Tests per key</summary>", ""]
    for key, row in m["items"].items():
        if row["tests"]:
            lines.append(f"**{key}**")
            lines += [f"- {'✅' if t['status'] == 'passed' else '❌'} `{t['suite']}` {t['test']}" for t in row["tests"]]
            lines.append("")
    lines.append("</details>")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    m = build(load_catalog(), parse_reports(args.reports))
    md = to_markdown(m)
    if args.markdown:
        args.markdown.write_text(md)
    if args.json:
        args.json.write_text(json.dumps(m, indent=2))
    if not args.markdown:
        print(md)

    if args.strict:
        bad = [k for k, r in m["items"].items() if r["status"] != "PASS"]
        if bad or m["unknown_keys"]:
            print(f"Traceability check failed: {bad + m['unknown_keys']}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
