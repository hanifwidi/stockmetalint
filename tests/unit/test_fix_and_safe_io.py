from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from stockmetalint import safe_io
from stockmetalint.csv_input import parse_csv_bytes
from stockmetalint.errors import ConfigError, OutputError
from stockmetalint.fixes.safe import DEFAULT_FIX_RULES, parse_fix_rules, plan_fixes
from stockmetalint.rules.registry import load_registry
from stockmetalint.validators.adobe import map_header
from stockmetalint.validators.context import LintContext
from tests.conftest import HEADER, csv_bytes, make_row

TEMPLATE = load_registry().template_header


def plan_for(data: bytes, rules: tuple[str, ...]):  # type: ignore[no-untyped-def]
    ctx = LintContext(load_registry())
    parsed = parse_csv_bytes(data, ctx.emit)
    assert parsed.header is not None
    mapping = map_header(ctx, parsed.header, 1)
    assert mapping is not None
    return plan_fixes(parsed, mapping, rules, TEMPLATE)


def test_parse_fix_rules() -> None:
    assert parse_fix_rules(None) == DEFAULT_FIX_RULES
    assert parse_fix_rules("nfc, trim-whitespace,nfc") == ("trim-whitespace", "nfc")
    with pytest.raises(ConfigError, match="unknown fix rule"):
        parse_fix_rules("rewrite-titles")
    with pytest.raises(ConfigError):
        parse_fix_rules(" , ")


def test_default_rules_only_touch_whitespace_and_never_filename_or_order() -> None:
    data = csv_bytes(
        [make_row(" a.jpg ", "  Title  ", "zeta,, alpha , Beta, alpha", " 11 ", " r1 ")]
    )
    plan = plan_for(data, DEFAULT_FIX_RULES)
    fields = plan.records[0]
    assert fields[0] == " a.jpg "  # Filename never modified
    assert fields[1] == "Title"
    assert fields[2] == "zeta, alpha, Beta, alpha"  # order kept, duplicates kept by default
    assert fields[3] == "11" and fields[4] == "r1"
    assert {c.rule for c in plan.changes} == {"trim-whitespace", "drop-empty-keywords"}


def test_dedupe_nfc_and_canonical_header_are_opt_in() -> None:
    header = ["filename", "Title", "Keywords", "Category", "Releases"]
    data = csv_bytes([make_row("a.jpg", "Café", "Sky, sun, sky, SUN, sea")], header=header)
    plan = plan_for(data, ("dedupe-keywords", "nfc", "canonical-header"))
    assert plan.header[0] == "Filename"
    assert plan.records[0][1] == "Café"
    assert plan.records[0][2] == "Sky, sun, sea"  # first occurrence wins, order preserved
    assert [c.rule for c in plan.changes] == ["canonical-header", "nfc", "dedupe-keywords"]


def test_rows_with_wrong_field_count_are_copied_unchanged() -> None:
    data = b"Filename,Title,Keywords,Category,Releases\na.jpg, T ,sky, sun,1,\n"
    plan = plan_for(data, DEFAULT_FIX_RULES)
    assert plan.skipped_rows == [1] and plan.changes == []


def test_render_preserves_bom_and_newline_and_is_idempotent() -> None:
    data = csv_bytes([make_row(keywords="a,, b")], newline="\r\n", bom=True)
    once = plan_for(data, DEFAULT_FIX_RULES).render()
    assert once.startswith(b"\xef\xbb\xbf") and b"\r\n" in once
    twice = plan_for(once, DEFAULT_FIX_RULES)
    assert twice.changes == [] and twice.render() == once


def test_formula_cells_detected_and_escape_is_explicit() -> None:
    data = csv_bytes([make_row("a.jpg", "=1+2", "@x, b, c")])
    plan = plan_for(data, DEFAULT_FIX_RULES)
    assert [(c.column, c.prefix) for c in plan.formula_cells] == [("Title", "="), ("Keywords", "@")]
    plan.escape_formulas()
    plan.scan_formulas()
    assert plan.formula_cells == []
    assert plan.records[0][1] == "'=1+2"
    assert [c.rule for c in plan.changes].count("formula-escape") == 2


# --------------------------------------------------------------------------- safe_io


def test_output_must_not_alias_source(tmp_path: Path) -> None:
    src = tmp_path / "batch.csv"
    src.write_text("x")
    with pytest.raises(OutputError, match="same file"):
        safe_io.check_output_path(src, protected=[src], overwrite=True)
    with pytest.raises(OutputError, match="same file"):
        safe_io.check_output_path(tmp_path / "." / "batch.csv", protected=[src], overwrite=True)
    os.link(src, tmp_path / "hardlink.csv")
    with pytest.raises(OutputError, match="same file"):
        safe_io.check_output_path(tmp_path / "hardlink.csv", protected=[src], overwrite=True)
    with pytest.raises(OutputError, match="directory"):
        safe_io.check_output_path(tmp_path, protected=[src], overwrite=True)
    other = tmp_path / "other.csv"
    other.write_text("y")
    with pytest.raises(OutputError, match="already exists"):
        safe_io.check_output_path(other, protected=[src], overwrite=False)
    safe_io.check_output_path(other, protected=[src], overwrite=True)
    safe_io.check_output_path(tmp_path / "new.csv", protected=[src], overwrite=False)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_output_symlink_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "batch.csv"
    src.write_text("x")
    os.symlink(src, tmp_path / "alias.csv")
    with pytest.raises(OutputError, match="symbolic link"):
        safe_io.check_output_path(tmp_path / "alias.csv", protected=[src], overwrite=True)
    os.symlink(tmp_path / "missing.csv", tmp_path / "dangling.csv")
    with pytest.raises(OutputError, match="symbolic link"):
        safe_io.check_output_path(tmp_path / "dangling.csv", protected=[src], overwrite=True)


def test_case_variant_alias_on_case_insensitive_platforms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "Batch.csv"
    src.write_text("x")
    monkeypatch.setattr(safe_io.sys, "platform", "darwin")
    with pytest.raises(OutputError, match=r"refers to the input|same file"):
        safe_io.check_output_path(tmp_path / "BATCH.CSV", protected=[src], overwrite=True)


def test_atomic_write_success_and_cleanup_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "sub" / "out.csv"
    safe_io.atomic_write_bytes(target, b"first")
    assert target.read_bytes() == b"first"

    def crash(_src: object, _dst: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(safe_io.os, "replace", crash)
    with pytest.raises(OutputError, match="No space left"):
        safe_io.atomic_write_bytes(target, b"second")
    assert target.read_bytes() == b"first"  # previous content intact
    assert [p.name for p in target.parent.iterdir()] == ["out.csv"]  # no temp file left


def test_atomic_write_permission_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def deny(*_a: object, **_k: object) -> tuple[int, str]:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(safe_io.tempfile, "mkstemp", deny)
    with pytest.raises(OutputError, match="Permission denied"):
        safe_io.atomic_write_bytes(tmp_path / "x.csv", b"data")


def test_sha256() -> None:
    assert safe_io.sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_header_constant_matches_registry() -> None:
    assert tuple(HEADER) == TEMPLATE
