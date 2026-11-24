# Requirements traceability

Every requirement, bug, and vulnerability the viewer addresses has a stable **key**
(`REQ-04`, `BUG-03`, …) defined in [`traceability.json`](traceability.json), along with
its GitHub issue number. Tests are tagged with keys, and every test report carries those
keys and the linked issues. That makes it possible to:

- show which automated tests verify each requirement and bug, and whether they passed
- close requirement and bug issues with evidence
- push results to TestRail automatically, linked to the GitHub issues

## Tagging tests

| Suite | How to tag | Example |
|---|---|---|
| Backend (pytest) | marker | `@pytest.mark.req("REQ-04", "BUG-05")` |
| E2E (Playwright) | `trace()` helper (adds `@REQ-04` tags and annotations) | `test("pages a table", trace("REQ-04"), async ({ page }) => …)` |
| Frontend unit (Vitest) | key in the test name | `it("[REQ-07] shows colormap selector", …)` |

Unknown keys fail fast: pytest raises a usage error, `trace()` throws, and the matrix
script reports them.

Run a single requirement's tests:

```bash
cd backend && pytest --req REQ-04 --req BUG-05       # backend tests for those keys
cd frontend && npx playwright test --grep @REQ-07     # e2e for REQ-07
```

## Reports

Every run writes JUnit XML:

| Suite | Report |
|---|---|
| Backend | `backend/test-results/junit-backend.xml` |
| Frontend unit | `frontend/test-results/junit-unit.xml` |
| E2E | `frontend/test-results/junit-e2e.xml` |

pytest and Playwright write the keys as `<property>` elements on each `<testcase>`:

```xml
<testcase name="test_repeated_group_fields_read_at_group_offsets" ...>
  <properties>
    <property name="requirement" value="REQ-04"/>
    <property name="bug" value="BUG-05"/>
    <property name="issue" value="NASA-PDS/pds4_tools_prototype#7"/>
    <property name="issue" value="NASA-PDS/pds4_tools_prototype#22"/>
    <property name="testrail_case_field" value="refs:NASA-PDS/pds4_tools_prototype#7,NASA-PDS/pds4_tools_prototype#22"/>
  </properties>
</testcase>
```

The `issue` and `testrail_case_field` properties appear once issue numbers are recorded
in `traceability.json` (see below).

### Traceability matrix

```bash
python traceability/trace_matrix.py --strict
```

It reads every `*.xml` JUnit report in `backend/test-results/`, `frontend/test-results/`
and `reports/`, and writes `trace-matrix.md` and `trace-matrix.json` to the repository root.

CI runs this after all test jobs. It posts the matrix to the workflow run summary and
uploads `trace-matrix.md`, `trace-matrix.json`, and the JUnit files as the
`traceability` artifact. With `--strict`, the job fails if any requirement or bug has no
test or a failing test.

### TestRail

The JUnit reports work with the TestRail CLI as-is. `testrail_case_field` sets each
case's **References** field to the linked GitHub issues:

```bash
pip install trcli
trcli -y -h https://<instance>.testrail.io --project "PDS" \
  --username "$TESTRAIL_USER" --key "$TESTRAIL_KEY" \
  parse_junit --title "pds4_tools_prototype CI ${GITHUB_RUN_ID}" \
  -f "reports/*.xml" --case-matcher auto
```

To automate this, add the command as a step in the `traceability` job, with TestRail
credentials stored as repository secrets.

## Creating and linking issues

`create_issues.py` creates one GitHub issue per catalog entry. It follows the NASA-PDS
`creating-pds-issues` conventions: org template bodies, labels, issue types and the
`jordanpadams` triage assignee. Every issue also gets the build label (`B19` by default;
change it with `--build-label`). The org adds new issues to project NASA-PDS/6
automatically. Each issue is attached as a sub-issue of the theme, and its number is
written back to `traceability.json`:

```bash
python traceability/create_issues.py --dry-run   # preview
python traceability/create_issues.py             # create (idempotent; skips entries with numbers)
```

Commit the updated `traceability.json` so reports carry issue links.

## Adding a requirement

1. Add an entry to `traceability.json` (`issue: null`).
2. Run `create_issues.py`.
3. Tag the tests that verify it.
4. Confirm the CI matrix shows it as PASS before closing the issue.
