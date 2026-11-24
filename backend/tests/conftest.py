"""Shared test fixtures for backend tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import clear_labels
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DATA_DIR = REPO_ROOT / "test_data"
TABLE_CHARACTER_XML = TEST_DATA_DIR / "table_character" / "Table_Character_Example.xml"
TABLE_CHARACTER_TAB = TEST_DATA_DIR / "table_character" / "Table_Character_Example.tab"
ARRAY_2D_IMAGE_XML = TEST_DATA_DIR / "array_2d_image" / "thermal_neutron_map.xml"
ARRAY_2D_IMAGE_DATA = TEST_DATA_DIR / "array_2d_image" / "thermal_neutron_map.img"
TABLE_DUP_COLS_XML = TEST_DATA_DIR / "table_character_dup_cols" / "ch3_cht_raw_20230824T12_625085705_v1.xml"
TABLE_DUP_COLS_CSV = TEST_DATA_DIR / "table_character_dup_cols" / "ch3_cht_raw_20230824T12_625085705_v1.csv"


@pytest.fixture(autouse=True)
def _uploads_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests exercise the upload API; tests of the default turn it back off."""
    from app import config

    monkeypatch.setattr(config, "UPLOAD_ENABLED", True)


@pytest.fixture
def client():
    clear_labels()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def table_character_xml() -> Path:
    return TABLE_CHARACTER_XML


@pytest.fixture
def table_character_tab() -> Path:
    return TABLE_CHARACTER_TAB


@pytest.fixture
def array_2d_image_xml() -> Path:
    return ARRAY_2D_IMAGE_XML


@pytest.fixture
def array_2d_image_data() -> Path:
    return ARRAY_2D_IMAGE_DATA


@pytest.fixture
def table_dup_cols_xml() -> Path:
    return TABLE_DUP_COLS_XML


@pytest.fixture
def table_dup_cols_csv() -> Path:
    return TABLE_DUP_COLS_CSV


# ---------------------------------------------------------------------------
# Requirement / bug traceability
#
# Tag tests with @pytest.mark.req("REQ-04", "BUG-05"). Keys are defined in
# traceability/traceability.json (which also holds the GitHub issue numbers).
# Each tag is written to the JUnit XML report (pytest --junitxml=...) as:
#   <property name="requirement" value="REQ-04"/>
#   <property name="issue" value="NASA-PDS/pds4_tools_prototype#12"/>
#   <property name="testrail_case_field" value="refs:NASA-PDS/pds4_tools_prototype#12,..."/>
# so TestRail (trcli parse_junit) and traceability/trace_matrix.py can link
# automated results back to requirement and bug issues.
# ---------------------------------------------------------------------------

TRACEABILITY = json.loads((REPO_ROOT / "traceability" / "traceability.json").read_text())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--req", action="append", default=[], metavar="KEY",
                     help="only run tests tagged with this requirement/bug key (repeatable)")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "req(*keys): requirement/bug keys from traceability/traceability.json")
    # Create the --junitxml report directory up front (CI and local runs alike).
    xmlpath = getattr(config.option, "xmlpath", None)
    if xmlpath:
        Path(xmlpath).parent.mkdir(parents=True, exist_ok=True)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    known = TRACEABILITY["items"]
    wanted = set(config.getoption("--req"))
    selected, deselected = [], []
    for item in items:
        keys = {k for marker in item.iter_markers("req") for k in marker.args}
        unknown = sorted(keys - set(known))
        if unknown:
            raise pytest.UsageError(f"{item.nodeid}: unknown traceability key(s) {unknown}")
        (selected if not wanted or keys & wanted else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture(autouse=True)
def _record_traceability(request: pytest.FixtureRequest, record_property) -> None:
    repo = TRACEABILITY["repository"]
    keys: list[str] = []
    for marker in request.node.iter_markers("req"):
        keys.extend(k for k in marker.args if k not in keys)
    refs = []
    for key in keys:
        entry = TRACEABILITY["items"][key]
        kind = "requirement" if entry["type"] == "requirement" else "bug"
        record_property(kind, key)
        if entry.get("issue"):
            ref = f"{repo}#{entry['issue']}"
            refs.append(ref)
            record_property("issue", ref)
    if refs:
        record_property("testrail_case_field", "refs:" + ",".join(refs))
