"""End-to-end flows through a real subprocess, plus performance and no-network guards."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

from stockmetalint.engine import LintOptions, lint_path
from tests.conftest import EXAMPLES, REPO_ROOT, csv_bytes, make_row, unique_rows


def run(*args: str | Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "src"),
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        **(env or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "stockmetalint", *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        timeout=120,
        check=False,
    )


@pytest.mark.slow
def test_generated_batch_lint_json_fix_and_checksum(tmp_path: Path) -> None:
    rows = [
        make_row("sunset-001.jpg", "Sunset over the harbour", "sunset, harbour,, boats"),
        make_row("sunset-002.jpg", "x" * 75, "sea, waves, rocks"),
    ]
    src = tmp_path / "batch.csv"
    src.write_bytes(csv_bytes(rows))
    digest = hashlib.sha256(src.read_bytes()).hexdigest()

    lint = run("lint", src, "--format", "json", "--output", tmp_path / "report.json")
    assert lint.returncode == 1 and lint.stdout == ""
    report = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert [
        (d["code"], d["row"], d["line"]) for d in report["diagnostics"] if d["severity"] == "error"
    ] == [("ADOBE-CSV-TITLE-LENGTH", 2, 3)]

    dry = run("fix", src)
    assert dry.returncode == 1 and "Dry run" in dry.stdout  # title error remains -> exit 1
    out = tmp_path / "proposed.csv"
    fix = run("fix", src, "--output", out)
    assert (
        fix.returncode == 1 and out.exists() and "sunset, harbour, boats" in out.read_text("utf-8")
    )
    assert hashlib.sha256(src.read_bytes()).hexdigest() == digest  # original untouched

    bad_config = run("lint", src, "--assets", tmp_path / "no-such-dir")
    assert bad_config.returncode == 2 and "not found" in bad_config.stderr


@pytest.mark.slow
def test_examples_exit_codes_via_subprocess() -> None:
    assert run("lint", EXAMPLES / "adobe-valid.csv").returncode == 0
    assert (
        run("lint", EXAMPLES / "adobe-valid.csv", "--assets", EXAMPLES / "assets").returncode == 0
    )
    invalid = run("lint", EXAMPLES / "adobe-invalid.csv", "--format", "json")
    assert invalid.returncode == 1 and json.loads(invalid.stdout)["summary"]["errors"] > 0
    assert run("doctor").returncode == 0


@pytest.mark.slow
def test_5000_row_batch_is_fast_and_bounded(tmp_path: Path) -> None:
    src = tmp_path / "big.csv"
    src.write_bytes(csv_bytes(unique_rows(5000)))
    assert src.stat().st_size < 1_000_000
    # Time and memory are measured in separate passes: tracemalloc itself slows
    # allocation-heavy code several-fold, which would distort the timing budget.
    started = time.perf_counter()
    report = lint_path(src, LintOptions(reproducible=True))
    elapsed = time.perf_counter() - started
    assert report.data_rows == 5000 and report.exit_code() == 0
    assert elapsed < 10, f"5,000 rows took {elapsed:.2f}s"
    tracemalloc.start()
    try:
        lint_path(src, LintOptions(reproducible=True))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 64 * 1024 * 1024, f"peak traced memory {peak} bytes"


def test_no_network_during_lint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    report = lint_path(
        EXAMPLES / "adobe-invalid.csv", LintOptions(assets_dir=EXAMPLES / "assets", inspect=True)
    )
    assert report.exit_code() == 1


def test_negative_control_limits_are_what_the_tests_depend_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the title limit were silently raised, the 71-character fixture would pass.

    This proves the boundary tests fail for the real reason (the limit), not setup.
    """
    from stockmetalint.engine import lint_bytes
    from stockmetalint.rules import registry as reg

    data = csv_bytes([make_row(title="x" * 71)])
    assert "ADOBE-CSV-TITLE-LENGTH" in [d.code for d in lint_bytes(data).diagnostics]
    real = reg.RuleRegistry.int_limit

    def loosened(self: reg.RuleRegistry, rule_id: str) -> int:
        return 1000 if rule_id == "ADOBE-CSV-TITLE-LENGTH" else real(self, rule_id)

    monkeypatch.setattr(reg.RuleRegistry, "int_limit", loosened)
    assert "ADOBE-CSV-TITLE-LENGTH" not in [d.code for d in lint_bytes(data).diagnostics]


def test_deterministic_ordering(tmp_path: Path) -> None:
    src = tmp_path / "b.csv"
    src.write_bytes((EXAMPLES / "adobe-invalid.csv").read_bytes())
    first = lint_path(src, LintOptions(reproducible=True, assets_dir=EXAMPLES / "assets"))
    second = lint_path(src, LintOptions(reproducible=True, assets_dir=EXAMPLES / "assets"))
    assert first == second
    keys = [d.sort_key() for d in first.diagnostics]
    assert keys == sorted(keys)
    file_level = [d.row is None for d in first.diagnostics]
    assert file_level == sorted(file_level, reverse=True)  # file-level findings first
