"""Cross-row integrity checks (duplicates and review warnings).

All checks are O(n) hash lookups so a 5,000-row batch stays fast. Each later
row is compared with the *first* row sharing its key.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from stockmetalint.textutil import collapse_whitespace, excerpt, keyword_key
from stockmetalint.validators.context import LintContext, RowView
from stockmetalint.validators.keywords import split_keywords

#: Identical keyword sets are only flagged for rows with at least this many keywords.
MIN_KEYWORDS_FOR_SET_CHECK = 3
#: Near-duplicate signature size (first N keywords, compared as a set).
NEAR_DUPLICATE_PREFIX = 10


def _where(row: RowView) -> str:
    return f"row {row.row} (line {row.line})"


def check_batch(ctx: LintContext, rows: list[RowView]) -> None:
    exact: dict[str, RowView] = {}
    by_nfc: dict[str, RowView] = {}
    by_case: dict[str, RowView] = {}
    titles: dict[str, RowView] = {}
    keyword_sets: dict[frozenset[str], RowView] = {}
    prefixes: dict[frozenset[str], tuple[RowView, frozenset[str]]] = {}

    for row in rows:
        if not row.aligned:
            continue
        name = row.filename
        if name and name.strip():
            loc: dict[str, Any] = {
                "line": row.line,
                "row": row.row,
                "column": "Filename",
                "filename": name,
            }
            nfc = unicodedata.normalize("NFC", name)
            folded = nfc.casefold()
            if name in exact:
                ctx.emit(
                    "BATCH-FILENAME-DUPLICATE",
                    f'Filename "{excerpt(name, 50)}" also appears in {_where(exact[name])}.',
                    **loc,
                    suggestion="Keep exactly one row per file.",
                )
            elif nfc in by_nfc:
                other = by_nfc[nfc]
                ctx.emit(
                    "BATCH-FILENAME-UNICODE-COLLISION",
                    f'Filename "{excerpt(name, 50)}" equals "{excerpt(other.filename or "", 50)}" in '
                    f"{_where(other)} after Unicode normalization.",
                    **loc,
                    suggestion="Use one consistent spelling (NFC) for the file and the CSV.",
                )
            elif folded in by_case:
                other = by_case[folded]
                ctx.emit(
                    "BATCH-FILENAME-CASE-COLLISION",
                    f'Filename "{excerpt(name, 50)}" differs only by case from '
                    f'"{excerpt(other.filename or "", 50)}" in {_where(other)}.',
                    **loc,
                    suggestion="Rename one file; case-insensitive file systems treat them as one.",
                )
            exact.setdefault(name, row)
            by_nfc.setdefault(nfc, row)
            by_case.setdefault(folded, row)

        title = row.title
        if title and title.strip():
            key = collapse_whitespace(title).casefold()
            if key in titles:
                ctx.emit(
                    "BATCH-TITLE-DUPLICATE",
                    f'Same title as {_where(titles[key])}: "{excerpt(title)}"',
                    line=row.line,
                    row=row.row,
                    column="Title",
                    filename=row.filename or None,
                    suggestion="Review: describe what is specific to this asset.",
                )
            else:
                titles[key] = row

        if row.keywords:
            keywords, _ = split_keywords(row.keywords)
            keys = [keyword_key(k.text) for k in keywords]
            full = frozenset(keys)
            loc = {
                "line": row.line,
                "row": row.row,
                "column": "Keywords",
                "filename": row.filename or None,
            }
            if len(full) >= MIN_KEYWORDS_FOR_SET_CHECK:
                if full in keyword_sets:
                    ctx.emit(
                        "BATCH-KEYWORDS-IDENTICAL",
                        f"Same keyword set as {_where(keyword_sets[full])} ({len(full)} keywords).",
                        **loc,
                        suggestion="Review: add keywords specific to this asset.",
                    )
                    continue
                keyword_sets[full] = row
            if len(keys) >= NEAR_DUPLICATE_PREFIX:
                prefix = frozenset(keys[:NEAR_DUPLICATE_PREFIX])
                if prefix in prefixes and prefixes[prefix][1] != full:
                    ctx.emit(
                        "BATCH-KEYWORDS-NEAR-DUPLICATE",
                        f"First {NEAR_DUPLICATE_PREFIX} keywords match {_where(prefixes[prefix][0])} "
                        "(as a set) while the full sets differ.",
                        **loc,
                        suggestion="Heuristic review: put the most specific keywords first.",
                    )
                else:
                    prefixes.setdefault(prefix, (row, full))
