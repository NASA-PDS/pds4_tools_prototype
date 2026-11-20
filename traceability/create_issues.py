#!/usr/bin/env python3
"""Create GitHub issues for every entry in traceability.json and record their numbers.

Follows the NASA-PDS `creating-pds-issues` conventions (NASA-PDS/pds-agent-skills):
  * Bodies mirror the org templates in NASA-PDS/.github (feature request, bug report,
    vulnerability, task, release theme), written to a temp file and passed with --body-file
  * Labels / issue type per template:
      requirement   -> labels "needs:triage,requirement"   type Feature
      bug           -> labels "bug,needs:triage"           type Bug
      vulnerability -> labels "security,bug,needs:triage"  type Bug
      task          -> labels "task,i&t.skip"              type Task
      theme         -> labels "theme,Epic,i&t.skip"        type Theme
  * Triage assignee defaults to jordanpadams (override with PDS_ISSUE_ASSIGNEE)
  * Every issue is attached as a sub-issue of the THEME (REST sub-issues API)
  * Every issue also gets the build label (default B19, see --build-label)
  * NASA-PDS repositories add new issues to the portfolio project (NASA-PDS/6) automatically

Idempotent: entries that already have an "issue" number are skipped. Numbers are written
back to traceability.json after each creation so a partial run can be resumed.

Uses only the REST API (`gh api`), so it also works where GraphQL is unavailable.

Usage:
  python traceability/create_issues.py [--dry-run] [--repo NASA-PDS/pds4_tools_prototype]
Requires an authenticated `gh` CLI with write access to the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "traceability.json"
ORDER = {"theme": 0, "requirement": 1, "vulnerability": 2, "bug": 3, "task": 4}
LABELS = {
    "requirement": "needs:triage,requirement",
    "bug": "bug,needs:triage",
    "vulnerability": "security,bug,needs:triage",
    "task": "task,i&t.skip",
    "theme": "theme,Epic,i&t.skip",
}
# Build label applied to every issue (override with --build-label; "" to omit).
DEFAULT_BUILD_LABEL = "B19"
TYPES = {"requirement": "Feature", "bug": "Bug", "vulnerability": "Bug", "task": "Task", "theme": "Theme"}
ASSIGNED = {"requirement", "bug", "vulnerability"}
VERIFY_NOTE = (
    "Verified by automated tests tagged `{key}` (pytest marker / Playwright tag / Vitest name). "
    "Results are reported per key in the CI traceability matrix and JUnit reports "
    "(see `traceability/README.md`)."
)


def gh(*args: str, capture: bool = True) -> str:
    result = subprocess.run(["gh", *args], check=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else ""


def refs(catalog: dict, keys: list[str]) -> str:
    out = []
    for k in keys:
        item = catalog["items"].get(k, {})
        out.append(f"- #{item['issue']} ({k})" if item.get("issue") else f"- {k}")
    return "\n".join(out) or "N/A"


def body_for(key: str, item: dict, catalog: dict) -> str:
    kind = item["type"]
    if kind == "requirement":
        return f"""## Checked for duplicates
Yes - I've already checked

## 🧑‍🔬 User Persona(s)
{item['persona']}

## 💪 Motivation
{item['motivation']}

## 📖 Additional Details
{item['details']}

**Traceability key:** `{key}`
{VERIFY_NOTE.format(key=key)}

## Acceptance Criteria

## ⚙️ Engineering Details

## 🎉 I&T
"""
    if kind in ("bug", "vulnerability"):
        heading = "🐛 Describe the vulnerability" if kind == "vulnerability" else "🐛 Describe the bug"
        return f"""## Checked for duplicates
Yes - I've already checked

## {heading}
{item['describe']}

## 🕵️ Expected behavior
{item['expected']}

## 📜 To Reproduce
{item['reproduce']}

## 🖥 Environment Info
- Version of this software: pds4_tools_prototype `master` prior to the review fixes PR
- Operating System: any

## 📚 Version of Software Used
Initial prototype (backend 0.1.0)

## 🩺 Test Data / Additional context
Found during code review. **Traceability key:** `{key}`
{VERIFY_NOTE.format(key=key)}

## 🦄 Related requirements
{refs(catalog, item.get('requirements', []))}

---
## For Internal Dev Team To Complete

## ⚙️ Engineering Details

## 🎉 Integration & Test
"""
    if kind == "task":
        return f"""## 💡 Description
{item['description']}

**Related requirements**
{refs(catalog, item.get('requirements', []))}
"""
    return f"""## Are you sure this is not a new requirement or bug?
Yes

## 💡 Description
{item['description']}

Requirements, bugs and tasks for this theme are attached as sub-issues. Each carries a
traceability key (`REQ-xx`, `BUG-xx`) used to tag automated tests.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print bodies; create nothing")
    ap.add_argument("--repo", help="override repository from traceability.json")
    ap.add_argument("--build-label", default=DEFAULT_BUILD_LABEL, help="build label for every issue (default B19)")
    args = ap.parse_args()

    catalog = json.loads(CATALOG.read_text())
    repo = args.repo or catalog["repository"]
    assignee = os.environ.get("PDS_ISSUE_ASSIGNEE", "jordanpadams")
    if not args.dry_run:
        gh("api", f"/repos/{repo}", "--jq", ".full_name")

    keys = sorted(catalog["items"], key=lambda k: (ORDER[catalog["items"][k]["type"]], k))
    parent_key = catalog.get("parent")
    for key in keys:
        item = catalog["items"][key]
        if item.get("issue"):
            print(f"{key}: already #{item['issue']}, skipping")
            continue
        body = body_for(key, item, catalog)
        if args.dry_run:
            build = f",{args.build_label}" if args.build_label else ""
            print(f"\n===== {key} [{item['type']}] {item['title']}\nlabels: {LABELS[item['type']]}{build}\n{body}")
            continue

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
            body_file = f.name
        try:
            cmd = ["api", "--method", "POST", f"/repos/{repo}/issues",
                   "-f", f"title={item['title']}", "-F", f"body=@{body_file}"]
            labels = LABELS[item["type"]].split(",") + ([args.build_label] if args.build_label else [])
            for label in labels:
                cmd += ["-f", f"labels[]={label}"]
            if item["type"] in ASSIGNED:
                cmd += ["-f", f"assignees[]={assignee}"]
            created = json.loads(gh(*cmd))
        finally:
            os.unlink(body_file)

        number, url, issue_id = created["number"], created["html_url"], created["id"]
        try:
            gh("api", "--method", "PATCH", f"/repos/{repo}/issues/{number}", "-f", f"type={TYPES[item['type']]}")
        except subprocess.CalledProcessError as e:
            print(f"  warning: could not set issue type on #{number}: {e.stderr.strip()}", file=sys.stderr)
        item["issue"] = number
        CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
        print(f"{key}: created {url}")

        if parent_key and key != parent_key and catalog["items"][parent_key].get("issue"):
            parent = catalog["items"][parent_key]["issue"]
            try:
                gh("api", "--method", "POST", f"/repos/{repo}/issues/{parent}/sub_issues",
                   "-F", f"sub_issue_id={issue_id}")
            except subprocess.CalledProcessError as e:
                print(f"  warning: could not attach #{number} to theme #{parent}: {e.stderr}", file=sys.stderr)


    if not args.dry_run:
        closing = [f"Closes #{catalog['items'][k]['issue']}" for k in keys
                   if catalog["items"][k]["type"] != "theme" and catalog["items"][k].get("issue")]
        print("\nPR closing keywords:\n" + "\n".join(closing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
