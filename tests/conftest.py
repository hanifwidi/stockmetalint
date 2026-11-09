"""Shared test helpers. All inputs are synthetic and generated in-test."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from stockmetalint.cli import main
from stockmetalint.domain import Report
from stockmetalint.engine import LintOptions, lint_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples"
HEADER = ["Filename", "Title", "Keywords", "Category", "Releases"]
GOOD_KEYWORDS = "lake, dawn, water, calm, nature"


def make_row(
    filename: str = "photo-001.jpg",
    title: str = "A calm lake at dawn",
    keywords: str = GOOD_KEYWORDS,
    category: str = "11",
    releases: str = "",
) -> list[str]:
    return [filename, title, keywords, category, releases]


def csv_bytes(
    rows: Sequence[Sequence[str]],
    header: Sequence[str] | None = HEADER,
    *,
    newline: str = "\n",
    bom: bool = False,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator=newline)
    if header is not None:
        writer.writerow(header)
    writer.writerows(rows)
    data = buffer.getvalue().encode("utf-8")
    return b"\xef\xbb\xbf" + data if bom else data


def unique_rows(count: int) -> list[list[str]]:
    """*count* valid rows with distinct filenames, titles and keyword sets."""
    return [
        make_row(f"img-{i:05d}.jpg", f"Synthetic test scene number {i}",
                 f"kw{i}a, kw{i}b, kw{i}c, landscape, nature")
        for i in range(count)
    ]


def lint(data: bytes, *, source_name: str = "batch.csv", **options: object) -> Report:
    return lint_bytes(data, source_name=source_name, options=LintOptions(**options))  # type: ignore[arg-type]


def codes(report: Report) -> list[str]:
    return [d.code for d in report.diagnostics]


@dataclass
class CliResult:
    code: int
    out: str
    err: str


@pytest.fixture
def run_cli(capsys: pytest.CaptureFixture[str]) -> Callable[..., CliResult]:
    def _run(*args: str | Path) -> CliResult:
        code = main([str(a) for a in args])
        captured = capsys.readouterr()
        return CliResult(code, captured.out, captured.err)

    return _run


@pytest.fixture
def write_csv(tmp_path: Path) -> Callable[..., Path]:
    def _write(rows: Sequence[Sequence[str]], name: str = "batch.csv", **kwargs: object) -> Path:
        path = tmp_path / name
        path.write_bytes(csv_bytes(rows, **kwargs))  # type: ignore[arg-type]
        return path

    return _write
