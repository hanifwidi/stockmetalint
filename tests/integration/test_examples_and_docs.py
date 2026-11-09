"""Examples and generated docs must match actual behaviour (no stale evidence)."""

from __future__ import annotations

from stockmetalint.engine import LintOptions, lint_path
from stockmetalint.reporters.rules_report import render_list_markdown
from stockmetalint.rules.registry import load_registry
from tests.conftest import EXAMPLES, REPO_ROOT


def test_valid_example_is_clean_with_and_without_assets() -> None:
    assert lint_path(EXAMPLES / "adobe-valid.csv").diagnostics == ()
    assert (
        lint_path(
            EXAMPLES / "adobe-valid.csv", LintOptions(assets_dir=EXAMPLES / "assets")
        ).diagnostics
        == ()
    )


def test_invalid_example_exact_error_set() -> None:
    report = lint_path(EXAMPLES / "adobe-invalid.csv", LintOptions(assets_dir=EXAMPLES / "assets"))
    errors = sorted((d.row or 0, d.code) for d in report.diagnostics if d.severity.value == "error")
    assert errors == [
        (1, "ADOBE-CSV-TITLE-LENGTH"),
        (2, "ADOBE-CSV-KEYWORDS-REQUIRED"),
        (2, "ASSET-CASE-MISMATCH"),
        (3, "ADOBE-CSV-FILENAME-PATH"),
        (4, "ADOBE-CSV-CATEGORY-FORMAT"),
        (4, "ADOBE-CSV-FILENAME-LENGTH"),
        (4, "ASSET-MISSING"),
        (5, "BATCH-FILENAME-DUPLICATE"),
        (6, "ADOBE-CSV-RELEASE-NAME-LENGTH"),
    ]
    assert report.exit_code() == 1


def test_example_assets_are_tiny_synthetic_jpegs() -> None:
    files = sorted(p for p in (EXAMPLES / "assets").iterdir())
    assert [p.name for p in files] == [
        "city-night-004.jpg",
        "coffee-cup-003.jpg",
        "pasar-pagi-005.jpg",
        "rice-terrace-002.jpg",
        "sunrise-beach-001.jpg",
    ]
    for path in files:
        data = path.read_bytes()
        assert data.startswith(b"\xff\xd8\xff") and len(data) < 2048


def test_rules_doc_is_up_to_date() -> None:
    expected = render_list_markdown(load_registry())
    actual = (REPO_ROOT / "docs" / "rules.md").read_text("utf-8")
    assert actual == expected, (
        "docs/rules.md is stale: run `stockmetalint rules list --format markdown`"
    )
