"""Boundary tests for source-backed Adobe CSV rules.

Each test first asserts the fixture really has the intended size, so a failure
points at the rule implementation, not at a broken fixture.
"""

from __future__ import annotations

import pytest

from stockmetalint.validators.adobe import path_problem
from tests.conftest import HEADER, codes, csv_bytes, lint, make_row, unique_rows


@pytest.mark.parametrize(("length", "flagged"), [(69, False), (70, False), (71, True)])
def test_title_length_boundary(length: int, flagged: bool) -> None:
    title = ("Sunrise " * 20)[: length - 1] + "x"
    assert len(title) == length
    assert ("ADOBE-CSV-TITLE-LENGTH" in codes(lint(csv_bytes([make_row(title=title)])))) is flagged


@pytest.mark.parametrize(("length", "flagged"), [(29, False), (30, False), (31, True)])
def test_filename_length_boundary(length: int, flagged: bool) -> None:
    name = "a" * (length - 4) + ".jpg"
    assert len(name) == length
    assert (
        "ADOBE-CSV-FILENAME-LENGTH" in codes(lint(csv_bytes([make_row(filename=name)])))
    ) is flagged


@pytest.mark.parametrize(
    ("count", "standard", "editorial"),
    [
        (0, ["ADOBE-CSV-KEYWORDS-REQUIRED"], ["ADOBE-CSV-KEYWORDS-REQUIRED"]),
        (1, [], []),
        (49, [], []),
        (50, [], ["ADOBE-GUIDANCE-KEYWORDS-49"]),
        (51, ["ADOBE-CSV-KEYWORDS-MAX"], ["ADOBE-CSV-KEYWORDS-MAX", "ADOBE-GUIDANCE-KEYWORDS-49"]),
    ],
)
def test_keyword_count_scopes(count: int, standard: list[str], editorial: list[str]) -> None:
    keywords = ", ".join(f"keyword{i}" for i in range(count))
    assert len([k for k in keywords.split(",") if k.strip()]) == count
    data = csv_bytes([make_row(keywords=keywords)])
    kw_codes = {
        "ADOBE-CSV-KEYWORDS-REQUIRED",
        "ADOBE-CSV-KEYWORDS-MAX",
        "ADOBE-GUIDANCE-KEYWORDS-49",
    }
    std = [c for c in codes(lint(data)) if c in kw_codes]
    edi = [c for c in codes(lint(data, profile="editorial")) if c in kw_codes]
    assert std == standard
    assert edi == editorial
    # The 49-keyword guidance never blocks: 50 keywords pass in both profiles.
    if count == 50:
        assert lint(data, profile="editorial").exit_code() == 0


@pytest.mark.parametrize(("rows", "flagged"), [(5000, False), (5001, True)])
def test_row_limit_boundary(rows: int, flagged: bool) -> None:
    report = lint(csv_bytes(unique_rows(rows)))
    assert report.data_rows == rows
    assert ("ADOBE-CSV-ROW-LIMIT" in codes(report)) is flagged


def _sized_csv(size: int) -> bytes:
    """A valid CSV of exactly *size* bytes, spread over many distinct rows (<= 5,000)."""
    total = len(csv_bytes([], header=HEADER))
    rows: list[list[str]] = []
    i = 0
    while True:
        row = make_row(
            f"img-{i:05d}.jpg", f"Synthetic scene {i}", ", ".join(f"k{i}x{j}" for j in range(20))
        )
        length = len(csv_bytes([row], header=None))
        if total + length > size - 100:
            break
        rows.append(row)
        total += length
        i += 1
    final = make_row("img-final.jpg", "Final padded row", "pad, q")
    pad = size - total - len(csv_bytes([final], header=None))
    final[2] += "q" * pad  # the cell is already quoted, so each char adds exactly one byte
    rows.append(final)
    return csv_bytes(rows)


@pytest.mark.parametrize(
    ("size", "error", "warning"),
    [
        (1_000_000, False, False),
        (1_000_001, False, True),
        (1_048_576, False, True),
        (1_048_577, True, False),
    ],
)
def test_file_size_boundaries(size: int, error: bool, warning: bool) -> None:
    data = _sized_csv(size)
    assert len(data) == size
    found = codes(lint(data))
    assert ("ADOBE-CSV-FILE-SIZE" in found) is error
    assert ("ADOBE-CSV-FILE-SIZE-DECIMAL" in found) is warning


def test_file_extension_rule() -> None:
    assert "ADOBE-CSV-FILE-TYPE" in codes(lint(csv_bytes([make_row()]), source_name="batch.txt"))
    assert "ADOBE-CSV-FILE-TYPE" not in codes(
        lint(csv_bytes([make_row()]), source_name="BATCH.CSV")
    )


def test_exact_header_passes_cleanly() -> None:
    report = lint(csv_bytes([make_row()]))
    assert report.diagnostics == () and report.exit_code() == 0


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (["filename", "Title", "Keywords", "Category", "Releases"], ["ADOBE-CSV-HEADER-NAME"]),
        (
            ["File Name", "Title", "Key words", "Category", "Releases"],
            ["ADOBE-CSV-HEADER-NAME", "ADOBE-CSV-HEADER-NAME"],
        ),
        (["Filename", "Title", "Keywrods", "Category", "Releases"], ["ADOBE-CSV-HEADER-NAME"]),
        (
            ["Filename", "Title", "Keywords", "Categories", "Release"],
            ["ADOBE-CSV-HEADER-NAME", "ADOBE-CSV-HEADER-NAME"],
        ),
        (
            ["Filename", "Title", "Keywords"],
            ["ADOBE-CSV-HEADER-OPTIONAL-MISSING", "ADOBE-CSV-HEADER-OPTIONAL-MISSING"],
        ),
        (["Filename", "Title", "Category", "Releases"], ["ADOBE-CSV-HEADER-REQUIRED"]),
        (
            ["Filename", "Title", "Keywords", "Category", "Releases", "Description"],
            ["ADOBE-CSV-HEADER-UNKNOWN"],
        ),
        (
            ["Filename", "Title", "Keywords", "Keywords", "Category", "Releases"],
            ["ADOBE-CSV-HEADER-DUPLICATE"],
        ),
        (["Title", "Filename", "Keywords", "Category", "Releases"], ["ADOBE-CSV-HEADER-ORDER"]),
    ],
)
def test_header_variants(header: list[str], expected: list[str]) -> None:
    row = ["photo-001.jpg", "A calm lake at dawn", "lake, dawn, water", "11", ""]
    row = row[: len(header)] + [""] * max(0, len(header) - len(row))
    if header[0] == "Title":
        row[0], row[1] = row[1], row[0]
    report = lint(csv_bytes([row], header=header))
    header_codes = sorted(c for c in codes(report) if c.startswith("ADOBE-CSV-HEADER"))
    assert header_codes == sorted(expected)


def test_missing_header_row_detected() -> None:
    report = lint(csv_bytes([make_row(), make_row("b.jpg")], header=None))
    assert codes(report).count("ADOBE-CSV-HEADER-ABSENT") == 1
    assert "looks like a file name" in report.diagnostics[0].message
    assert report.fatal


def test_header_misspelling_still_maps_column_for_row_checks() -> None:
    header = ["Filename", "title", "Keywords", "Category", "Releases"]
    report = lint(csv_bytes([make_row(title="x" * 71)], header=header))
    assert {"ADOBE-CSV-HEADER-NAME", "ADOBE-CSV-TITLE-LENGTH"} <= set(codes(report))


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("../secret.jpg", "traversal"),
        ("..", "traversal"),
        ("dir/photo.jpg", "separator"),
        ("dir\\photo.jpg", "separator"),
        ("/etc/passwd.jpg", "absolute"),
        ("\\\\server\\x.jpg", "absolute"),
        ("C:\\Users\\me\\a.jpg", "drive"),
        ("c:a.jpg", "drive"),
        ("https://x.test/a.jpg", "URL"),
        (".", "directory"),
        ("photo.jpg", None),
        ("my photo (1).jpg", None),
    ],
)
def test_path_problem(value: str, problem: str | None) -> None:
    result = path_problem(value)
    assert (result is None) if problem is None else (problem in (result or ""))


def test_filename_rules() -> None:
    rows = [
        make_row(filename=""),
        make_row(filename="../up.jpg"),
        make_row(filename="noextension"),
        make_row(filename=".jpg"),
        make_row(filename="CON.jpg"),
        make_row(filename="bad?.jpg"),
        make_row(filename="trailingdot."),
    ]
    found = codes(lint(csv_bytes(rows)))
    assert "ADOBE-CSV-FILENAME-REQUIRED" in found
    assert "ADOBE-CSV-FILENAME-PATH" in found
    assert found.count("ADOBE-CSV-FILENAME-EXTENSION") == 3  # noextension, .jpg, trailingdot.
    assert found.count("META-FILENAME-PORTABILITY") == 3  # CON, '?', trailing dot


def test_title_rules_and_unicode_counting() -> None:
    emoji_title = "Sunset " + "\U0001f305" * 3 + "x" * 60  # 70 code points, 73 UTF-16 units
    assert len(emoji_title) == 70
    decomposed = "e\u0301" * 36  # 72 code points, 36 after NFC
    rows = [
        make_row(title=""),
        make_row(filename="b.jpg", title=emoji_title),
        make_row(filename="c.jpg", title="Beach, sea and sky"),
        make_row(filename="d.jpg", title=decomposed),
    ]
    report = lint(csv_bytes(rows))
    found = codes(report)
    assert "ADOBE-CSV-TITLE-REQUIRED" in found
    assert "META-LENGTH-UTF16" in found and found.count("ADOBE-CSV-TITLE-LENGTH") == 1
    assert "ADOBE-CSV-TITLE-COMMA" in found
    length = next(d for d in report.diagnostics if d.code == "ADOBE-CSV-TITLE-LENGTH")
    assert "72 characters (36 after NFC normalization)" in length.message


@pytest.mark.parametrize(
    ("category", "code"),
    [
        ("11", None),
        ("1", None),
        ("21", None),
        (" 7 ", None),
        ("", None),
        ("abc", "ADOBE-CSV-CATEGORY-FORMAT"),
        ("\uff11\uff11", "ADOBE-CSV-CATEGORY-FORMAT"),
        ("-3", "ADOBE-CSV-CATEGORY-FORMAT"),
        ("11.0", "ADOBE-CSV-CATEGORY-FORMAT"),
        ("0", "ADOBE-CSV-CATEGORY-UNKNOWN"),
        ("22", "ADOBE-CSV-CATEGORY-UNKNOWN"),
    ],
)
def test_category(category: str, code: str | None) -> None:
    found = [
        c
        for c in codes(lint(csv_bytes([make_row(category=category)])))
        if c.startswith("ADOBE-CSV-CATEGORY-") and c != "ADOBE-CSV-CATEGORY-RECOMMENDED"
    ]
    assert found == ([code] if code else [])


def test_category_recommended_is_one_file_level_info() -> None:
    rows = [make_row(f"p{i}.jpg", f"Title number {i}", f"a{i}, b{i}, c{i}", "") for i in range(3)]
    report = lint(csv_bytes(rows))
    rec = [d for d in report.diagnostics if d.code == "ADOBE-CSV-CATEGORY-RECOMMENDED"]
    assert len(rec) == 1 and rec[0].row is None and "3 of 3 rows" in rec[0].message
    assert report.exit_code() == 0


def test_release_names() -> None:
    ok = "r" * 30
    bad = "r" * 31
    found = codes(lint(csv_bytes([make_row(releases=f"{ok}, {bad},")])))
    assert found.count("ADOBE-CSV-RELEASE-NAME-LENGTH") == 1


def test_header_only_file_has_no_rows() -> None:
    report = lint(csv_bytes([], header=HEADER))
    assert report.data_rows == 0 and report.exit_code() == 0
