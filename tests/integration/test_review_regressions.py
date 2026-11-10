"""Regression tests for defects found by the adversarial review (2026-11-10).

Each test reproduces the original failure scenario and asserts the fixed behaviour.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest

from stockmetalint import inspection
from stockmetalint.engine import LintOptions, lint_path, timestamp
from tests.conftest import CliResult, codes, csv_bytes, lint, make_row

Run = Callable[..., CliResult]
MALFORMED_MIDDLE = (
    b"Filename,Title,Keywords,Category,Releases\n"
    b'a.jpg,Red apple on table,"apple, fruit, red",1,\n'
    b'b.jpg,"Green "pear" photo,"pear, fruit",1,\n'
    b'c.jpg,Yellow banana bunch,"banana, fruit",1,\n'
)


def test_fix_refuses_when_parsing_stopped(run_cli: Run, tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    src.write_bytes(MALFORMED_MIDDLE)
    out = tmp_path / "out.csv"
    result = run_cli("fix", src, "--output", out)
    assert result.code == 1
    assert not out.exists() and not (tmp_path / "out.csv.audit.json").exists()
    assert "could not be fully parsed" in result.err
    assert json.loads(run_cli("fix", src, "--format", "json").out)["exit_code"] == 1


def test_ignoring_a_fatal_rule_cannot_turn_failure_into_pass(run_cli: Run, tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    src.write_bytes(MALFORMED_MIDDLE)
    assert run_cli("lint", src, "--ignore", "CSV-MALFORMED").code == 1
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    assert run_cli("lint", empty, "--ignore", "CSV-FILE-EMPTY").code == 1


def test_audit_log_respects_overwrite_and_never_hits_source(run_cli: Run, tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    src.write_bytes(csv_bytes([make_row()]))
    before = src.read_bytes()
    other = tmp_path / "keep.json"
    other.write_text("precious")
    out = tmp_path / "out.csv"
    assert run_cli("fix", src, "--output", out, "--audit-log", other).code == 2
    assert other.read_text() == "precious" and not out.exists()
    assert run_cli("fix", src, "--output", out, "--audit-log", src, "--overwrite").code == 2
    assert src.read_bytes() == before and not out.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs need POSIX")
def test_special_file_output_is_refused(run_cli: Run, tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    src.write_bytes(csv_bytes([make_row()]))
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    result = run_cli("lint", src, "--output", fifo)
    assert result.code == 2 and "not a regular file" in result.err


def test_exact_header_wins_over_earlier_near_miss() -> None:
    header = ["Filename", "Titles", "Title", "Keywords", "Category", "Releases"]
    report = lint(
        csv_bytes([["a.jpg", "x" * 80, "Short title", "a, b, c", "1", ""]], header=header)
    )
    found = codes(report)
    assert "ADOBE-CSV-HEADER-UNKNOWN" in found  # "Titles" is a separate, unknown column
    assert "ADOBE-CSV-TITLE-LENGTH" not in found  # the exact "Title" column is the one checked


def test_huge_category_number_does_not_crash() -> None:
    report = lint(csv_bytes([make_row(category="9" * 5000)]))
    assert "ADOBE-CSV-CATEGORY-UNKNOWN" in codes(report)


def test_invisible_only_required_cells_are_empty() -> None:
    zw = "​‍"
    found = codes(lint(csv_bytes([make_row(filename=zw, title=zw, keywords=f"{zw}, ⁠")])))
    for code in (
        "ADOBE-CSV-FILENAME-REQUIRED",
        "ADOBE-CSV-TITLE-REQUIRED",
        "ADOBE-CSV-KEYWORDS-REQUIRED",
    ):
        assert code in found


def test_nfc_nfd_keywords_are_duplicates_and_fix_removes_them(run_cli: Run, tmp_path: Path) -> None:
    keywords = "café, café, tea"
    assert "META-KEYWORD-DUPLICATE" in codes(lint(csv_bytes([make_row(keywords=keywords)])))
    src = tmp_path / "in.csv"
    src.write_bytes(csv_bytes([make_row(keywords=keywords)]))
    out = tmp_path / "out.csv"
    assert run_cli("fix", src, "--output", out, "--fix-rules", "nfc,dedupe-keywords").code == 0
    assert "café, tea" in out.read_text("utf-8")


def test_near_duplicate_still_detected_after_identical_row() -> None:
    top = ", ".join(f"k{i}" for i in range(10))
    rows = [
        make_row("a.jpg", "A", top + ", x"),
        make_row("b.jpg", "B", top + ", x"),
        make_row("c.jpg", "C", top + ", y"),
    ]
    found = codes(lint(csv_bytes(rows)))
    assert "BATCH-KEYWORDS-IDENTICAL" in found and "BATCH-KEYWORDS-NEAR-DUPLICATE" in found


def test_blank_row_diagnostics_are_bounded_and_fix_records_dropped_blanks(
    run_cli: Run, tmp_path: Path
) -> None:
    data = (
        csv_bytes([make_row()])
        + b"\n" * 5000
        + csv_bytes([make_row("b.jpg", "Other")], header=None)
    )
    report = lint(data)
    blanks = [d for d in report.diagnostics if d.code == "CSV-BLANK-ROW"]
    assert len(blanks) == 21
    assert any("5000 in total" in d.message for d in blanks)
    src = tmp_path / "in.csv"
    src.write_bytes(
        csv_bytes([make_row()]) + b",,,,\n" + csv_bytes([make_row("b.jpg", "O")], header=None)
    )
    summary = json.loads(run_cli("fix", src, "--format", "json").out)
    assert [c["rule"] for c in summary["changes"]] == ["drop-blank-record"]


def test_undecodable_file_name_does_not_crash_json(run_cli: Run, tmp_path: Path) -> None:
    if sys.platform in ("win32", "darwin"):
        pytest.skip("needs a file system that allows non-UTF-8 names")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / os.fsdecode(b"bad\xff.jpg")).write_bytes(b"x")
    src = tmp_path / "in.csv"
    src.write_bytes(csv_bytes([make_row()]))
    result = run_cli("lint", src, "--assets", assets, "--format", "json")
    assert result.code == 1 and "internal error" not in result.err
    assert "ASSET-ORPHAN" in result.out


def test_oversized_png_is_not_decoded(tmp_path: Path) -> None:
    image = pytest.importorskip("PIL.Image")
    assets = tmp_path / "assets"
    assets.mkdir()
    buffer = BytesIO()
    image.new("1", (8000, 8000)).save(buffer, "PNG")  # 64 MP, tiny file
    (assets / "big.png").write_bytes(buffer.getvalue())
    report = lint(csv_bytes([make_row("big.png")]), assets_dir=assets, inspect=True)
    assert "too large to decode safely" in " ".join(d.message for d in report.diagnostics)


def test_decode_errors_do_not_leak_absolute_paths(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "photo-001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 40)
    report = lint(csv_bytes([make_row()]), assets_dir=assets, inspect=True)
    assert str(tmp_path) not in json.dumps([d.message for d in report.diagnostics])


def test_ffprobe_lookup_passes_explicit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_which(cmd: str, mode: int = os.F_OK | os.X_OK, path: str | None = None) -> None:
        seen["path"] = path

    monkeypatch.setattr(inspection.shutil, "which", fake_which)
    inspection.find_ffprobe()
    assert seen["path"] is not None


def test_release_extension_is_case_insensitive(tmp_path: Path) -> None:
    rel = tmp_path / "rel"
    rel.mkdir()
    (rel / "John Doe.JPG").write_bytes(b"x")
    assert "ASSET-RELEASE-MISSING" not in codes(
        lint(csv_bytes([make_row(releases="John Doe")]), releases_dir=rel)
    )


def test_out_of_range_source_date_epoch_and_str_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "9" * 30)
    assert timestamp(reproducible=True) is None
    (tmp_path / "photo-001.jpg").write_bytes(b"x")
    src = tmp_path / "in.csv"
    src.write_bytes(csv_bytes([make_row()]))
    report = lint_path(src, LintOptions(assets_dir=str(tmp_path)))  # type: ignore[arg-type]
    assert report.assets_checked


def test_usage_errors_escape_control_characters(run_cli: Run) -> None:
    result = run_cli("lint", "a.csv", "--format", "\x1b[2Jevil")
    assert result.code == 2 and "\x1b[2J" not in result.err


def test_no_color_and_fail_on_warning_json(
    run_cli: Run, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from stockmetalint.reporters.text_report import should_use_color

    class Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    assert should_use_color(Tty(), "auto")  # type: ignore[arg-type]
    monkeypatch.setenv("NO_COLOR", "1")
    assert not should_use_color(Tty(), "auto")  # type: ignore[arg-type]
    assert not should_use_color(Tty(), "never")  # type: ignore[arg-type]
    src = tmp_path / "in.csv"
    src.write_bytes(csv_bytes([make_row(title="Sea, sky")]))
    data = json.loads(run_cli("lint", src, "--format", "json", "--fail-on-warning").out)
    assert data["summary"]["exit_code"] == 1
