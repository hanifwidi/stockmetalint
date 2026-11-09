"""Adobe Stock CSV rules: file, header and per-field checks.

Limits come from the registry (``rules/adobe_csv_2026_06.json``).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import PurePath

from stockmetalint.csv_input import ParsedCsv
from stockmetalint.textutil import code_points, excerpt, nfc_length, utf16_units
from stockmetalint.validators.context import ColumnMap, LintContext, RowView

_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_DIGITS_RE = re.compile(r"[0-9]+")
_WINDOWS_INVALID = frozenset('<>:"|?*')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


# --------------------------------------------------------------------------- file level


def check_file(ctx: LintContext, source_name: str, size_bytes: int) -> None:
    suffix = PurePath(source_name).suffix
    if suffix.lower() != ".csv":
        shown = suffix or "no extension"
        ctx.emit("ADOBE-CSV-FILE-TYPE", f"The metadata file has {shown!s}; it must be a .csv file.",
                 suggestion="Export as 'CSV UTF-8 (Comma delimited)' and use the .csv extension.")
    hard = ctx.registry.int_limit("ADOBE-CSV-FILE-SIZE")
    soft = ctx.registry.int_limit("ADOBE-CSV-FILE-SIZE-DECIMAL")
    if size_bytes > hard:
        ctx.emit("ADOBE-CSV-FILE-SIZE",
                 f"The file is {size_bytes:,} bytes; the limit is 1 MB ({hard:,} bytes = 1 MiB).",
                 suggestion="Split the batch into smaller CSV files.")
    elif size_bytes > soft:
        ctx.emit("ADOBE-CSV-FILE-SIZE-DECIMAL",
                 f"The file is {size_bytes:,} bytes: over {soft:,} bytes (1 MB decimal) but within "
                 f"{hard:,} bytes (1 MiB).",
                 suggestion="Stay at or below 1,000,000 bytes to be safe under either definition.")


def check_row_limit(ctx: LintContext, data_rows: int) -> None:
    limit = ctx.registry.int_limit("ADOBE-CSV-ROW-LIMIT")
    if data_rows > limit:
        ctx.emit("ADOBE-CSV-ROW-LIMIT", f"The file has {data_rows:,} data rows; the limit is {limit:,}.",
                 suggestion=f"Split the batch into files of at most {limit:,} rows.")


# --------------------------------------------------------------------------- header


def _header_key(name: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", name).casefold())


def _canonical_for(name: str, template: tuple[str, ...]) -> str | None:
    key = _header_key(name)
    if not key:
        return None
    for canonical in template:
        ckey = _header_key(canonical)
        variants = {ckey, ckey + "s", ckey.removesuffix("s")}
        if ckey.endswith("y"):
            variants.add(ckey[:-1] + "ies")
        if key in variants:
            return canonical
    keys = {_header_key(c): c for c in template}
    close = difflib.get_close_matches(key, list(keys), n=1, cutoff=0.8)
    return keys[close[0]] if close else None


def map_header(ctx: LintContext, header: tuple[str, ...], header_line: int) -> ColumnMap | None:
    """Validate the header row and return canonical-column -> index, or None if absent."""
    template = ctx.registry.template_header
    resolved: list[tuple[int, str, str | None]] = []
    for index, raw in enumerate(header):
        canonical = raw if raw in template else _canonical_for(raw, template)
        resolved.append((index, raw, canonical))

    if not any(canonical for _, _, canonical in resolved):
        first = header[0] if header else ""
        looks_like_data = "." in first and " " not in first.strip()
        hint = (f' The first cell "{excerpt(first, 40)}" looks like a file name, so the header row '
                "may be missing.") if looks_like_data else ""
        ctx.emit("ADOBE-CSV-HEADER-ABSENT",
                 "The first record contains none of the template columns "
                 f"({', '.join(template)}).{hint}",
                 line=header_line,
                 suggestion="Add the template header as the first line: " + ",".join(template))
        return None

    mapping: ColumnMap = {}
    for index, raw, canonical in resolved:
        if canonical is None:
            ctx.emit("ADOBE-CSV-HEADER-UNKNOWN",
                     f'Column "{excerpt(raw, 40)}" (position {index + 1}) is not in the template.',
                     line=header_line, column=raw,
                     suggestion="Remove the column; the template columns are " + ", ".join(template) + ".")
            continue
        if raw != canonical:
            ctx.emit("ADOBE-CSV-HEADER-NAME",
                     f'Header "{excerpt(raw, 40)}" (position {index + 1}) must be spelled exactly '
                     f'"{canonical}".',
                     line=header_line, column=canonical,
                     suggestion=f'Rename the header cell to "{canonical}" (the fix rule '
                                "canonical-header can do this).")
        if canonical in mapping:
            ctx.emit("ADOBE-CSV-HEADER-DUPLICATE",
                     f'Column "{canonical}" appears more than once (positions {mapping[canonical] + 1} '
                     f"and {index + 1}); only the first is checked.",
                     line=header_line, column=canonical,
                     suggestion="Keep a single column with this name.")
            continue
        mapping[canonical] = index

    for canonical in template:
        if canonical in mapping:
            continue
        if canonical in ctx.registry.required_columns:
            ctx.emit("ADOBE-CSV-HEADER-REQUIRED", f'Required column "{canonical}" is missing.',
                     line=header_line, column=canonical,
                     suggestion="Use the template header: " + ",".join(template))
        else:
            ctx.emit("ADOBE-CSV-HEADER-OPTIONAL-MISSING",
                     f'Optional column "{canonical}" is absent.', line=header_line, column=canonical,
                     suggestion="Keep the column (cells may be empty) to match the template exactly.")

    expected = [c for c in template if c in mapping]
    actual = sorted(mapping, key=mapping.__getitem__)
    if actual != expected:
        ctx.emit("ADOBE-CSV-HEADER-ORDER",
                 f"Columns are ordered {', '.join(actual)}; the template order is {', '.join(expected)}.",
                 line=header_line,
                 suggestion="Reorder the columns to match the template.")
    return mapping


# --------------------------------------------------------------------------- rows


def build_rows(ctx: LintContext, parsed: ParsedCsv, mapping: ColumnMap) -> list[RowView]:
    """Map records onto template columns; report field-count mismatches."""
    assert parsed.header is not None  # noqa: S101 - guaranteed by caller
    expected = len(parsed.header)
    rows: list[RowView] = []
    for record in parsed.records:
        count = len(record.fields)
        aligned = count <= expected
        if count != expected:
            if count > expected:
                detail = ("content checks are skipped for this row. Unquoted commas inside Keywords are "
                          "the usual cause")
                tip = 'Wrap the whole keyword list in double quotes: "sky, sun, beach".'
            else:
                detail = "missing trailing cells are treated as empty"
                tip = "Add the missing cells (they may be empty) so every row matches the header."
            ctx.emit("CSV-ROW-FIELD-COUNT",
                     f"Row has {count} fields but the header has {expected}; {detail}.",
                     line=record.line, row=record.row, suggestion=tip)

        def cell(name: str, fields: tuple[str, ...] = record.fields) -> str | None:
            index = mapping.get(name)
            if index is None:
                return None
            return fields[index] if index < len(fields) else ""

        rows.append(RowView(record, aligned, cell("Filename"), cell("Title"), cell("Keywords"),
                            cell("Category"), cell("Releases")))
    return rows


def path_problem(value: str) -> str | None:
    """Why *value* is a path rather than a bare file name, or None."""
    if "://" in value:
        return "looks like a URL"
    if _DRIVE_RE.match(value):
        return "starts with a Windows drive letter"
    if value.startswith(("/", "\\")):
        return "is an absolute path"
    parts = re.split(r"[\\/]", value)
    if any(part == ".." for part in parts) or value.strip() == "..":
        return "contains '..' path traversal"
    if len(parts) > 1:
        return "contains a directory separator"
    if value.strip() == ".":
        return "is a directory reference"
    return None


def _portability_problems(value: str) -> list[str]:
    problems: list[str] = []
    invalid = sorted({ch for ch in value if ch in _WINDOWS_INVALID})
    if invalid:
        problems.append("contains " + " ".join(invalid))
    stem = value.split(".", 1)[0].rstrip(" ").upper()
    if stem in _WINDOWS_RESERVED:
        problems.append(f"uses the reserved Windows device name {stem}")
    if value.endswith((" ", ".")):
        problems.append("ends with a space or dot")
    return problems


def check_filename(ctx: LintContext, row: RowView, value: str) -> None:
    loc = {"line": row.line, "row": row.row, "column": "Filename"}
    if not value.strip():
        ctx.emit("ADOBE-CSV-FILENAME-REQUIRED", "Filename is empty.", **loc,
                 suggestion="Enter the exact media file name including its extension.")
        return
    shown = excerpt(value, 50)
    problem = path_problem(value)
    if problem:
        ctx.emit("ADOBE-CSV-FILENAME-PATH", f'Filename "{shown}" {problem}; it must be a bare file name.',
                 filename=value, **loc,
                 suggestion="Use only the file name, e.g. " + (PurePath(value.replace("\\", "/")).name or
                                                               "photo.jpg") + ".")
    limit = ctx.registry.int_limit("ADOBE-CSV-FILENAME-LENGTH")
    length = code_points(value)
    if length > limit:
        ctx.emit("ADOBE-CSV-FILENAME-LENGTH",
                 f'Filename "{shown}" is {length} characters; the limit is {limit} including the '
                 "extension.", filename=value, **loc,
                 suggestion=f"Rename the file (and this cell) to {limit} characters or fewer.")
    elif utf16_units(value) > limit:
        ctx.emit("META-LENGTH-UTF16",
                 f"Filename is {length} code points but {utf16_units(value)} UTF-16 code units "
                 f"(limit {limit}).", filename=value, **loc,
                 suggestion="Avoid emoji and other astral characters in file names.")
    if problem:
        return
    stem, dot, ext = value.strip().rpartition(".")
    if not dot or not stem or not ext.strip():
        ctx.emit("ADOBE-CSV-FILENAME-EXTENSION",
                 f'Filename "{shown}" has no file extension.', filename=value, **loc,
                 suggestion="Include the extension exactly as on disk, e.g. sunset-001.jpg.")
    problems = _portability_problems(value)
    if problems:
        ctx.emit("META-FILENAME-PORTABILITY",
                 f'Filename "{shown}" is not portable to Windows: {"; ".join(problems)}.',
                 filename=value, **loc, suggestion="Use letters, digits, '-', '_' and '.' only.")


def check_title(ctx: LintContext, row: RowView, value: str) -> None:
    loc = {"line": row.line, "row": row.row, "column": "Title", "filename": row.filename or None}
    if not value.strip():
        ctx.emit("ADOBE-CSV-TITLE-REQUIRED", "Title is empty.", **loc,
                 suggestion="Write a short, accurate description of the asset.")
        return
    limit = ctx.registry.int_limit("ADOBE-CSV-TITLE-LENGTH")
    length = code_points(value)
    if length > limit:
        nfc = nfc_length(value)
        nfc_note = f" ({nfc} after NFC normalization)" if nfc != length else ""
        ctx.emit("ADOBE-CSV-TITLE-LENGTH",
                 f'Title is {length} characters{nfc_note}; the limit is {limit}: "{excerpt(value)}"',
                 **loc,
                 suggestion=f"Shorten the title to {limit} characters or fewer. StockMetaLint never "
                            "truncates text.")
    elif utf16_units(value) > limit:
        ctx.emit("META-LENGTH-UTF16",
                 f"Title is {length} code points but {utf16_units(value)} UTF-16 code units "
                 f"(limit {limit}); web forms may count it as too long.", **loc,
                 suggestion="Remove emoji or other astral characters, or shorten the title.")
    if "," in value:
        ctx.emit("ADOBE-CSV-TITLE-COMMA", f'Title contains a comma: "{excerpt(value)}"', **loc,
                 suggestion="Rephrase without commas; keep keyword lists in the Keywords column.")


def check_category(ctx: LintContext, row: RowView, value: str) -> None:
    text = value.strip()
    if not text:
        return
    loc = {"line": row.line, "row": row.row, "column": "Category", "filename": row.filename or None}
    if not _DIGITS_RE.fullmatch(text):
        ctx.emit("ADOBE-CSV-CATEGORY-FORMAT", f'Category "{excerpt(value, 30)}" is not a number.', **loc,
                 suggestion="Use the category number with ASCII digits, e.g. 11 (Landscapes in the "
                            "seed list).")
        return
    number = int(text)
    if number not in ctx.registry.categories:
        low, high = min(ctx.registry.categories), max(ctx.registry.categories)
        ctx.emit("ADOBE-CSV-CATEGORY-UNKNOWN",
                 f"Category {number} is not in the seed category list ({low}-{high}; list not fully "
                 "verified).", **loc,
                 suggestion="Check the number against Adobe's current category list.")


def check_releases(ctx: LintContext, row: RowView, value: str) -> None:
    limit = ctx.registry.int_limit("ADOBE-CSV-RELEASE-NAME-LENGTH")
    for name in (part.strip() for part in value.split(",")):
        if name and code_points(name) > limit:
            ctx.emit("ADOBE-CSV-RELEASE-NAME-LENGTH",
                     f'Release "{excerpt(name, 40)}" is {code_points(name)} characters; the limit is '
                     f"{limit}.", line=row.line, row=row.row, column="Releases",
                     filename=row.filename or None,
                     suggestion=f"Rename the release file to {limit} characters or fewer and update "
                                "this cell.")


def check_category_summary(ctx: LintContext, rows: list[RowView]) -> None:
    candidates = [r for r in rows if r.aligned and r.category is not None]
    missing = [r for r in candidates if not r.category or not r.category.strip()]
    if missing:
        sample = ", ".join(str(r.row) for r in missing[:10]) + ("..." if len(missing) > 10 else "")
        ctx.emit("ADOBE-CSV-CATEGORY-RECOMMENDED",
                 f"{len(missing)} of {len(candidates)} rows have no Category (rows {sample}).",
                 suggestion="Add a category number; Adobe highly recommends categories.")
