"""Cell hygiene and security checks shared by all columns."""

from __future__ import annotations

from typing import Any

from stockmetalint.textutil import (
    control_characters,
    describe_char,
    formula_prefix,
    invisible_characters,
    is_nfc,
)
from stockmetalint.validators.context import LintContext, RowView


def _describe(chars: list[str]) -> str:
    unique = list(dict.fromkeys(chars))
    shown = ", ".join(describe_char(ch) for ch in unique[:3])
    return shown + (f" and {len(unique) - 3} more" if len(unique) > 3 else "")


def check_cells(ctx: LintContext, row: RowView) -> None:
    for column, value in row.cells():
        if not value:
            continue
        loc: dict[str, Any] = {
            "line": row.line,
            "row": row.row,
            "column": column,
            "filename": row.filename or None,
        }
        is_filename = column == "Filename"
        if value != value.strip() and value.strip():
            ctx.emit(
                "META-WHITESPACE",
                f"{column} has leading or trailing whitespace.",
                **loc,
                suggestion=(
                    "Rename consistently; whitespace in Filename breaks exact matching."
                    if is_filename
                    else "Trim it (fix rule: trim-whitespace)."
                ),
            )
        controls = control_characters(value)
        if controls:
            ctx.emit(
                "META-CONTROL-CHAR",
                f"{column} contains control characters: {_describe(controls)}.",
                **loc,
                suggestion="Remove line breaks and tabs from the cell.",
            )
        hidden = invisible_characters(value, strict=is_filename)
        if hidden:
            ctx.emit(
                "SEC-INVISIBLE-CHAR",
                f"{column} contains bidirectional or invisible characters: {_describe(hidden)}.",
                **loc,
                suggestion="Retype the text without hidden characters.",
            )
        if not is_nfc(value):
            ctx.emit(
                "META-UNICODE-NFC",
                f"{column} is not in Unicode NFC form.",
                **loc,
                suggestion=(
                    "Rename file and cell consistently."
                    if is_filename
                    else "Normalize to NFC (fix rule: nfc)."
                ),
            )
        prefix = formula_prefix(value)
        if prefix is not None:
            shown = {"\t": "a tab", "\r": "a carriage return"}.get(prefix, f'"{prefix}"')
            ctx.emit(
                "SEC-FORMULA-PREFIX",
                f"{column} starts with {shown}; a spreadsheet may evaluate it as a formula.",
                **loc,
                suggestion="Rephrase so the cell does not start with = + - @ or a control "
                "character.",
            )
