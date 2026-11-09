"""Safe CSV loading: byte-level guards, strict UTF-8 decoding and strict parsing.

Nothing read from the file is ever evaluated or executed. Positions are kept
as two separate numbers:

* ``line`` - 1-based physical line where a record starts (a quoted field can
  span several lines; ``end_line`` is where it ends);
* ``row``  - 1-based data-row index, excluding the header and blank records.
"""

from __future__ import annotations

import csv
import io
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stockmetalint.errors import InputError

#: Safety cap for reading an input file into memory. The Adobe limit is 1 MB,
#: so 32 MiB leaves room to report oversized files without unbounded memory use.
DEFAULT_MAX_INPUT_BYTES = 32 * 1024 * 1024
UTF8_BOM = b"\xef\xbb\xbf"
_MAX_ENCODING_REPORTS = 5

_TEXT_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "UTF-32 LE"),
    (b"\x00\x00\xfe\xff", "UTF-32 BE"),
    (b"\xff\xfe", "UTF-16 LE"),
    (b"\xfe\xff", "UTF-16 BE"),
)
_BINARY_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "a ZIP container such as an Excel .xlsx workbook"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "an OLE2 file such as a legacy Excel .xls workbook"),
    (b"%PDF-", "a PDF document"),
    (b"\xff\xd8\xff", "a JPEG image"),
    (b"\x89PNG\r\n\x1a\n", "a PNG image"),
    (b"GIF87a", "a GIF image"),
    (b"GIF89a", "a GIF image"),
)


class Emit(Protocol):
    """Callback used to report diagnostics (implemented by the lint context)."""

    def __call__(
        self,
        rule_id: str,
        message: str,
        *,
        line: int | None = ...,
        row: int | None = ...,
        column: str | None = ...,
        filename: str | None = ...,
        suggestion: str | None = ...,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CsvRecord:
    row: int
    line: int
    end_line: int
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedCsv:
    size_bytes: int
    had_bom: bool
    newline: str
    header: tuple[str, ...] | None
    header_line: int | None
    records: tuple[CsvRecord, ...]
    #: True when the content could not be decoded at all (no header/records).
    unreadable: bool
    #: True when parsing stopped early at a malformed record.
    parse_stopped: bool


def read_input_bytes(path: Path, max_bytes: int = DEFAULT_MAX_INPUT_BYTES) -> bytes:
    """Read a regular file, refusing directories, devices and oversized input."""
    try:
        st = path.stat()
    except FileNotFoundError:
        raise InputError(f"input file not found: {path}") from None
    except PermissionError:
        raise InputError(f"permission denied reading input: {path}") from None
    except OSError as exc:
        raise InputError(f"cannot access input {path}: {exc.strerror or exc}") from None
    if stat.S_ISDIR(st.st_mode):
        raise InputError(f"input is a directory, not a CSV file: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise InputError(f"input is not a regular file: {path}")
    if st.st_size > max_bytes:
        raise InputError(
            f"input is {st.st_size} bytes, above the processing safety cap of {max_bytes} bytes "
            "(raise it with --max-input-bytes if this is intentional)"
        )
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except PermissionError:
        raise InputError(f"permission denied reading input: {path}") from None
    except OSError as exc:
        raise InputError(f"cannot read input {path}: {exc.strerror or exc}") from None
    if len(data) > max_bytes:
        raise InputError(f"input grew above the processing safety cap of {max_bytes} bytes")
    return data


def line_of_offset(data: bytes, offset: int) -> int:
    """1-based line of a byte offset, counting CRLF, LF and lone CR like ``csv`` does."""
    head = data[:offset]
    return head.count(b"\n") + head.count(b"\r") - head.count(b"\r\n") + 1


def invalid_utf8_offsets(data: bytes, limit: int = _MAX_ENCODING_REPORTS) -> list[int]:
    """Byte offsets of up to *limit* invalid UTF-8 sequences."""
    offsets: list[int] = []
    start = 0
    while start < len(data) and len(offsets) < limit:
        try:
            data[start:].decode("utf-8")
        except UnicodeDecodeError as exc:
            offsets.append(start + exc.start)
            start += max(exc.end, exc.start + 1)
        else:
            break
    return offsets


def detect_newline(text: str) -> str:
    lf = text.find("\n")
    cr = text.find("\r")
    if cr != -1 and (lf == -1 or cr < lf):
        return "\r\n" if text.startswith("\r\n", cr) else "\r"
    if lf != -1:
        return "\n"
    return "\r\n"


def _unreadable(size: int, had_bom: bool = False) -> ParsedCsv:
    return ParsedCsv(size, had_bom, "\r\n", None, None, (), unreadable=True, parse_stopped=False)


def parse_csv_bytes(data: bytes, emit: Emit) -> ParsedCsv:
    """Decode and parse *data*, emitting structural/encoding diagnostics via *emit*."""
    size = len(data)
    if size == 0:
        emit(
            "CSV-FILE-EMPTY",
            "The file is empty (0 bytes).",
            suggestion="Export the spreadsheet again as 'CSV UTF-8 (Comma delimited)'.",
        )
        return _unreadable(size)

    for bom, name in _TEXT_BOMS:
        if data.startswith(bom):
            emit(
                "ADOBE-CSV-ENCODING-UTF8",
                f"The file starts with a {name} byte-order mark; it is not UTF-8.",
                line=1,
                suggestion="Save as 'CSV UTF-8 (Comma delimited)' (Excel) or UTF-8 (other editors).",
            )
            return _unreadable(size)
    for signature, description in _BINARY_SIGNATURES:
        if data.startswith(signature):
            emit(
                "CSV-FILE-BINARY",
                f"The file content is {description}, not CSV text.",
                suggestion="Export the sheet as 'CSV UTF-8 (Comma delimited)' and lint that file.",
            )
            return _unreadable(size)
    nul = data.find(b"\x00")
    if nul != -1:
        emit(
            "CSV-NUL-BYTE",
            f"NUL byte at byte offset {nul} (line {line_of_offset(data, nul)}); "
            "the file is probably UTF-16 or binary.",
            line=line_of_offset(data, nul),
            suggestion="Save the file as UTF-8 CSV.",
        )
        return _unreadable(size)

    had_bom = data.startswith(UTF8_BOM)
    body = data[len(UTF8_BOM) :] if had_bom else data
    if had_bom:
        emit(
            "CSV-ENCODING-BOM",
            "UTF-8 byte-order mark found and accepted (Excel 'CSV UTF-8' writes one).",
            line=1,
        )
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        for offset in invalid_utf8_offsets(body):
            absolute = offset + (len(UTF8_BOM) if had_bom else 0)
            line = line_of_offset(data, absolute)
            emit(
                "ADOBE-CSV-ENCODING-UTF8",
                f"Invalid UTF-8 byte 0x{data[absolute]:02X} at byte offset {absolute} (line {line}).",
                line=line,
                suggestion="Re-save as 'CSV UTF-8 (Comma delimited)'; legacy encodings such as "
                "Windows-1252 are not UTF-8.",
            )
        return _unreadable(size, had_bom)

    if not text.strip():
        emit(
            "CSV-FILE-EMPTY",
            "The file contains only whitespace" + (" and a byte-order mark." if had_bom else "."),
        )
        return _unreadable(size, had_bom)

    return _parse_text(text, size, had_bom, emit)


def _parse_text(text: str, size: int, had_bom: bool, emit: Emit) -> ParsedCsv:
    reader = csv.reader(io.StringIO(text, newline=""), dialect="excel", strict=True)
    header: tuple[str, ...] | None = None
    header_line: int | None = None
    records: list[CsvRecord] = []
    pending_blank: list[tuple[int, bool]] = []  # (line, had_fields)
    parse_stopped = False
    row_index = 0
    while True:
        start_line = reader.line_num + 1
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            where = (
                f"starting at line {start_line}"
                if reader.line_num == start_line
                else f"starting at line {start_line} (parser stopped at line {reader.line_num})"
            )
            emit(
                "CSV-MALFORMED",
                f"Malformed CSV record {where}: {exc}.",
                line=start_line,
                suggestion="Check for an unclosed double quote or text after a closing quote. "
                'Quotes inside a quoted cell must be doubled ("").',
            )
            parse_stopped = True
            break
        if not fields or all(not f.strip() for f in fields):
            if header is None:
                emit(
                    "CSV-BLANK-ROW",
                    "Blank record before the header row.",
                    line=start_line,
                    suggestion="The header must be the first line of the file.",
                )
            else:
                pending_blank.append((start_line, bool(fields)))
            continue
        if header is None:
            header = tuple(fields)
            header_line = start_line
            continue
        for blank_line, _ in pending_blank:
            emit(
                "CSV-BLANK-ROW",
                "Blank or all-empty record between data rows (skipped).",
                line=blank_line,
                suggestion="Delete the empty line.",
            )
        pending_blank.clear()
        row_index += 1
        records.append(CsvRecord(row_index, start_line, reader.line_num, tuple(fields)))

    # Trailing truly-blank lines are harmless; trailing ",,,," records are not.
    for blank_line, had_fields in pending_blank:
        if had_fields:
            emit(
                "CSV-BLANK-ROW",
                "All-empty record at the end of the file (for example ',,,,' "
                "exported from formatted spreadsheet rows).",
                line=blank_line,
                suggestion="Delete the empty rows in the spreadsheet before exporting.",
            )
    return ParsedCsv(
        size_bytes=size,
        had_bom=had_bom,
        newline=detect_newline(text),
        header=header,
        header_line=header_line,
        records=tuple(records),
        unreadable=False,
        parse_stopped=parse_stopped,
    )


def display_name(path: Path, *, show_paths: bool) -> str:
    """Report-safe name: basename by default so home directories don't leak."""
    return os.fspath(path) if show_paths else path.name
