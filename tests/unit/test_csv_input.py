from __future__ import annotations

from pathlib import Path

import pytest

from stockmetalint.csv_input import (
    detect_newline,
    invalid_utf8_offsets,
    line_of_offset,
    parse_csv_bytes,
    read_input_bytes,
)
from stockmetalint.errors import InputError
from tests.conftest import GOOD_KEYWORDS, codes, csv_bytes, lint, make_row


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, rule_id: str, message: str, **kw: object) -> None:
        self.calls.append((rule_id, {"message": message, **kw}))

    def ids(self) -> list[str]:
        return [c[0] for c in self.calls]


def test_line_and_row_numbers_stay_distinct_with_multiline_fields() -> None:
    data = (
        b"Filename,Title,Keywords,Category,Releases\n"
        b'a.jpg,"Line one\nline two",kw,1,\n'
        b"b.jpg,Title,kw,1,\n"
    )
    rec = Recorder()
    parsed = parse_csv_bytes(data, rec)
    assert [(r.row, r.line, r.end_line) for r in parsed.records] == [(1, 2, 3), (2, 4, 4)]
    assert parsed.records[0].fields[1] == "Line one\nline two"


def test_quoted_keyword_commas_are_one_cell() -> None:
    parsed = parse_csv_bytes(csv_bytes([make_row(keywords="a, b, c, d")]), Recorder())
    assert parsed.records[0].fields == (
        "photo-001.jpg",
        "A calm lake at dawn",
        "a, b, c, d",
        "11",
        "",
    )


def test_bom_is_accepted_and_reported_as_info() -> None:
    report = lint(csv_bytes([make_row()], bom=True))
    assert codes(report) == ["CSV-ENCODING-BOM"]
    assert report.exit_code() == 0


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "CSV-FILE-EMPTY"),
        (b"\xef\xbb\xbf  \n\n", "CSV-FILE-EMPTY"),
        (b"PK\x03\x04rest-of-xlsx", "CSV-FILE-BINARY"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1xls", "CSV-FILE-BINARY"),
        (b"\xff\xd8\xff\xe0jpeg", "CSV-FILE-BINARY"),
        ("Filename,Title\n".encode("utf-16"), "ADOBE-CSV-ENCODING-UTF8"),
        (b"Filename,Title\x00,Keywords\n", "CSV-NUL-BYTE"),
    ],
)
def test_unreadable_inputs_are_fatal(data: bytes, code: str) -> None:
    report = lint(data)
    assert code in codes(report)
    assert report.fatal and report.data_rows is None and report.exit_code() == 1


def test_invalid_utf8_reports_offsets_and_lines() -> None:
    data = csv_bytes([make_row()]) + "café.jpg,Título,a,1,\n".encode("cp1252")
    # Setup sanity: the fixture really is invalid UTF-8.
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    report = lint(data)
    enc = [d for d in report.diagnostics if d.code == "ADOBE-CSV-ENCODING-UTF8"]
    assert len(enc) == 2 and {d.line for d in enc} == {3}
    assert "0xE9" in enc[0].message


def test_invalid_utf8_offsets_limit() -> None:
    assert invalid_utf8_offsets(b"ok") == []
    assert invalid_utf8_offsets(b"\xff" * 50, limit=3) == [0, 1, 2]


@pytest.mark.parametrize(
    ("data", "line"),
    [
        (b'Filename,Title,Keywords\na.jpg,"unterminated,kw\nb.jpg,t,k\n', 2),
        (b'Filename,Title,Keywords\na.jpg,"quoted"junk,kw\n', 2),
    ],
)
def test_malformed_quotes_stop_parsing_with_location(data: bytes, line: int) -> None:
    report = lint(data)
    bad = [d for d in report.diagnostics if d.code == "CSV-MALFORMED"]
    assert len(bad) == 1 and bad[0].line == line
    assert report.fatal and report.exit_code() == 1


def test_rows_before_malformed_record_are_still_checked() -> None:
    data = csv_bytes([make_row(title="")]) + b'b.jpg,"oops,kw,1,\n'
    report = lint(data)
    assert {"ADOBE-CSV-TITLE-REQUIRED", "CSV-MALFORMED"} <= set(codes(report))


def test_blank_records() -> None:
    data = (
        b"\nFilename,Title,Keywords,Category,Releases\n"
        b"a.jpg,Title one here,a b c,1,\n\n"
        b"b.jpg,Title two here,d e f,1,\n,,,,\n\n"
    )
    report = lint(data)
    blanks = [d for d in report.diagnostics if d.code == "CSV-BLANK-ROW"]
    assert [d.line for d in blanks] == [1, 4, 6]  # before header, between rows, trailing ",,,,"
    assert report.data_rows == 2


def test_field_count_mismatch() -> None:
    data = (
        b"Filename,Title,Keywords,Category,Releases\n"
        b"a.jpg,Title,sky, sun, sea,1,\n"  # unquoted commas -> 7 fields
        b"b.jpg,Title,kw\n"
    )  # 3 fields
    report = lint(data)
    mismatches = [d for d in report.diagnostics if d.code == "CSV-ROW-FIELD-COUNT"]
    assert [d.row for d in mismatches] == [1, 2]
    assert "skipped" in mismatches[0].message
    # Row 1 content is not checked (columns unreliable), so no keyword findings for it.
    assert not [d for d in report.diagnostics if d.row == 1 and d.code != "CSV-ROW-FIELD-COUNT"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_line_endings(newline: str) -> None:
    data = csv_bytes(
        [make_row(), make_row("photo-002.jpg", "Another calm lake", "a, b, c")], newline=newline
    )
    rec = Recorder()
    parsed = parse_csv_bytes(data, rec)
    assert parsed.newline == newline
    assert [r.line for r in parsed.records] == [2, 3]
    assert line_of_offset(data, len(data)) == 4


def test_detect_newline_default() -> None:
    assert detect_newline("single line") == "\r\n"


def test_read_input_guards(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="not found"):
        read_input_bytes(tmp_path / "missing.csv")
    with pytest.raises(InputError, match="directory"):
        read_input_bytes(tmp_path)
    big = tmp_path / "big.csv"
    big.write_bytes(b"x" * 101)
    with pytest.raises(InputError, match="safety cap"):
        read_input_bytes(big, max_bytes=100)
    assert read_input_bytes(big, max_bytes=101) == b"x" * 101


def test_field_larger_than_csv_limit_is_malformed() -> None:
    data = csv_bytes([make_row(title="x" * 140_000, keywords=GOOD_KEYWORDS)])
    assert "CSV-MALFORMED" in codes(lint(data))
