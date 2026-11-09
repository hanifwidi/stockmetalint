"""CLI behaviour: commands, exit codes, stdout/stderr separation, JSON schema."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from stockmetalint import __version__
from tests.conftest import EXAMPLES, REPO_ROOT, CliResult, make_row

SCHEMA = json.loads(
    (REPO_ROOT / "src/stockmetalint/schemas/report-v1.schema.json").read_text("utf-8")
)
Run = Callable[..., CliResult]


def test_version_and_help(run_cli: Run) -> None:
    result = run_cli("--version")
    assert result.code == 0 and result.out.strip() == f"stockmetalint {__version__}"
    for args in (["--help"], ["lint", "--help"], ["fix", "--help"], ["rules", "show", "--help"]):
        assert run_cli(*args).code == 0
    assert "exit status" in run_cli("--help").out


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["lint"],
        ["bogus"],
        ["lint", "x.csv", "--platform", "shutterstock"],
        ["lint", "x.csv", "--format", "xml"],
        ["lint", "x.csv", "--max-input-bytes", "0"],
        ["fix", "x.csv", "--dry-run", "--output", "y.csv"],
        ["rules"],
    ],
)
def test_usage_errors_exit_2(run_cli: Run, args: list[str]) -> None:
    result = run_cli(*args)
    assert result.code == 2 and result.out == ""


def test_valid_example_exits_0(run_cli: Run) -> None:
    result = run_cli("lint", EXAMPLES / "adobe-valid.csv", "--platform", "adobe-csv")
    assert result.code == 0 and "PASS (exit 0)" in result.out and result.err == ""


def test_invalid_example_exits_1_with_row_diagnostics(run_cli: Run) -> None:
    result = run_cli(
        "lint",
        EXAMPLES / "adobe-invalid.csv",
        "--platform",
        "adobe-csv",
        "--assets",
        EXAMPLES / "assets",
    )
    assert result.code == 1
    assert "line 2 · row 1 · Title" in result.out and "ADOBE-CSV-TITLE-LENGTH" in result.out
    assert "ASSET-CASE-MISMATCH" in result.out


def _json(result: CliResult) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(result.out)
    jsonschema.validate(data, SCHEMA)
    return data


def test_json_output_is_pure_and_schema_valid(run_cli: Run) -> None:
    result = run_cli("lint", EXAMPLES / "adobe-invalid.csv", "--format", "json")
    data = _json(result)
    assert result.code == 1 and data["summary"]["exit_code"] == 1
    assert data["source_file"] == "adobe-invalid.csv"  # basename only by default
    first = data["diagnostics"][0]
    assert set(first) == {
        "severity",
        "code",
        "scope",
        "source_url",
        "line",
        "row",
        "column",
        "filename",
        "message",
        "suggestion",
    }


def test_json_report_to_file_and_paths(run_cli: Run, tmp_path: Path) -> None:
    out = tmp_path / "reports" / "validation.json"
    result = run_cli("lint", EXAMPLES / "adobe-invalid.csv", "--format", "json", "--output", out)
    assert (
        result.code == 1 and result.out == "" and "report written to validation.json" in result.err
    )
    _json(CliResult(0, out.read_text("utf-8"), ""))
    shown = run_cli("lint", EXAMPLES / "adobe-valid.csv", "--format", "json", "--show-paths")
    assert Path(json.loads(shown.out)["source_file"]).parts[-2:] == ("examples", "adobe-valid.csv")


def test_lint_output_cannot_overwrite_input(run_cli: Run, write_csv: Callable[..., Path]) -> None:
    src = write_csv([make_row()])
    before = src.read_bytes()
    result = run_cli("lint", src, "--output", src)
    assert result.code == 2 and "same file" in result.err and src.read_bytes() == before


def test_fail_on_warning_and_ignore(run_cli: Run, write_csv: Callable[..., Path]) -> None:
    src = write_csv([make_row(title="Sea, sky and sand")])
    assert run_cli("lint", src).code == 0
    assert run_cli("lint", src, "--fail-on-warning").code == 1
    assert run_cli("lint", src, "--fail-on-warning", "--ignore", "adobe-csv-title-comma").code == 0
    bad = run_cli("lint", src, "--ignore", "NOT-A-RULE")
    assert bad.code == 2 and "unknown rule ID" in bad.err


def test_runtime_input_errors_exit_2(
    run_cli: Run, tmp_path: Path, write_csv: Callable[..., Path]
) -> None:
    assert run_cli("lint", tmp_path / "missing.csv").code == 2
    assert run_cli("lint", tmp_path).code == 2
    src = write_csv([make_row()])
    assert "not found" in run_cli("lint", src, "--assets", tmp_path / "nope").err
    assert "require --assets" in run_cli("lint", src, "--inspect").err
    assert run_cli("lint", src, "--max-input-bytes", "10").code == 2


def test_unicode_paths(run_cli: Run, tmp_path: Path) -> None:
    folder = tmp_path / "fötos 写真"
    folder.mkdir()
    src = folder / "bätch 日本.csv"
    src.write_bytes(b"Filename,Title,Keywords,Category,Releases\na.jpg,Lake,a, b,1,\n")
    assert run_cli("lint", src).code == 1  # field-count error, but the path itself works


def test_text_report_escapes_terminal_sequences(
    run_cli: Run, write_csv: Callable[..., Path]
) -> None:
    src = write_csv([make_row(title="Evil \x1b[2J title " + "x" * 70)])
    result = run_cli("lint", src, "--color", "always")
    assert "\x1b[2J" not in result.out and "\\x1b[2J" in result.out
    assert "\x1b[31m" not in run_cli("lint", src).out  # auto: not a TTY -> no color


def test_reproducible_json_is_byte_identical(run_cli: Run, monkeypatch: pytest.MonkeyPatch) -> None:
    args = ("lint", EXAMPLES / "adobe-invalid.csv", "--format", "json", "--reproducible")
    first, second = run_cli(*args).out, run_cli(*args).out
    assert first == second and json.loads(first)["checked_at"] is None
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")
    assert json.loads(run_cli(*args).out)["checked_at"] == "2026-01-01T00:00:00Z"
    normal = json.loads(run_cli("lint", EXAMPLES / "adobe-invalid.csv", "--format", "json").out)
    assert normal["checked_at"].endswith("Z")


def test_rules_commands(run_cli: Run) -> None:
    listing = run_cli("rules", "list", "--platform", "adobe-csv")
    assert listing.code == 0 and "ADOBE-CSV-TITLE-LENGTH" in listing.out
    data = json.loads(run_cli("rules", "list", "--format", "json").out)
    assert len(data["rules"]) == 72
    show = run_cli("rules", "show", "ADOBE-CSV-TITLE-LENGTH")
    assert show.code == 0 and "Limit           70" in show.out
    assert (
        json.loads(run_cli("rules", "show", "adobe-csv-title-length", "--format", "json").out)[
            "limit"
        ]
        == 70
    )
    missing = run_cli("rules", "show", "ADOBE-CSV-TITLE-LENGHT")
    assert missing.code == 2 and "Did you mean: ADOBE-CSV-TITLE-LENGTH" in missing.err


def test_doctor(run_cli: Run) -> None:
    text = run_cli("doctor")
    assert text.code == 0 and "UNVERIFIED" in text.out and "no network requests" in text.out
    data = json.loads(run_cli("doctor", "--format", "json").out)
    assert data["rule_profiles"][0]["verification"] == "unverified"


def test_fix_dry_run_writes_nothing(run_cli: Run, write_csv: Callable[..., Path]) -> None:
    src = write_csv([make_row(keywords="sky,, sun, sea")])
    before = set(src.parent.iterdir())
    result = run_cli("fix", src, "--platform", "adobe-csv", "--dry-run")
    assert result.code == 0 and "Dry run: no files were written." in result.out
    assert "[drop-empty-keywords]" in result.out
    assert set(src.parent.iterdir()) == before


def test_fix_output_audit_and_source_untouched(
    run_cli: Run, write_csv: Callable[..., Path]
) -> None:
    src = write_csv(
        [make_row(keywords="sky,, sun, sea"), make_row("b.jpg", "Second title", "x, y, z")]
    )
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    out = src.parent / "out" / "proposed.csv"
    result = run_cli("fix", src, "--output", out, "--format", "json", "--reproducible")
    summary = json.loads(result.out)
    assert result.code == 0 and summary["written"] and summary["mode"] == "write"
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest
    audit = json.loads((out.parent / "proposed.csv.audit.json").read_text("utf-8"))
    assert audit["source_sha256"] == digest
    assert audit["output_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert audit["changes"][0]["rule"] == "drop-empty-keywords" and audit["created_at"] is None
    again = run_cli("fix", src, "--output", out)
    assert again.code == 2 and "already exists" in again.err
    assert run_cli("fix", src, "--output", out, "--overwrite").code == 0


def test_fix_refuses_source_and_formula_cells(run_cli: Run, write_csv: Callable[..., Path]) -> None:
    src = write_csv([make_row(title="=HYPERLINK(1)")])
    before = src.read_bytes()
    same = run_cli("fix", src, "--output", src)
    assert same.code == 2 and src.read_bytes() == before
    out = src.parent / "p.csv"
    refused = run_cli("fix", src, "--output", out)
    assert refused.code == 1 and "Refused: nothing was written." in refused.out and not out.exists()
    escaped = run_cli("fix", src, "--output", out, "--formula-policy", "escape")
    assert escaped.code == 0 and "'=HYPERLINK(1)" in out.read_text("utf-8")
    assert run_cli("fix", src, "--audit-log", src.parent / "a.json").code == 2


def test_fix_unreadable_csv_exits_1(run_cli: Run, tmp_path: Path) -> None:
    src = tmp_path / "bad.csv"
    src.write_bytes(b"\xff\xfeF\x00")
    assert run_cli("fix", src).code == 1
    data = json.loads(run_cli("fix", src, "--format", "json").out)
    assert data["exit_code"] == 1 and data["changes"] == []


def test_internal_errors_exit_2(
    run_cli: Run, monkeypatch: pytest.MonkeyPatch, write_csv: Callable[..., Path]
) -> None:
    src = write_csv([make_row()])

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("stockmetalint.cli.analyze_path", boom)
    result = run_cli("lint", src)
    assert result.code == 2 and "internal error: RuntimeError" in result.err
    monkeypatch.setenv("STOCKMETALINT_DEBUG", "1")
    assert "Traceback" in run_cli("lint", src).err
