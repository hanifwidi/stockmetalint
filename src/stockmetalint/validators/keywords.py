"""Keyword parsing and per-row keyword checks.

Keywords are the comma-separated items of one CSV cell. Order is preserved
everywhere; originals are reported as written and never rewritten here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from stockmetalint.textutil import (
    SUSPICIOUS_KEYWORD_SEPARATORS,
    excerpt,
    keyword_key,
    keyword_key_nfkc,
)
from stockmetalint.validators.context import LintContext, RowView

#: HEURISTIC list of technical/filler terms (StockMetaLint's own, see docs/rules.md).
LOW_VALUE_TERMS = frozenset(
    {
        "jpg",
        "jpeg",
        "png",
        "tif",
        "tiff",
        "raw",
        "dng",
        "heic",
        "mov",
        "mp4",
        "eps",
        "svg",
        "4k",
        "8k",
        "hd",
        "uhd",
        "full hd",
        "fullhd",
        "high resolution",
        "high res",
        "hi res",
        "high quality",
        "royalty free",
        "stock",
        "stock photo",
        "stock image",
        "stock footage",
        "image",
        "picture",
        "photo",
    }
)
_LOW_VALUE_PATTERNS = (
    re.compile(r"f/?\d+(?:\.\d+)?"),  # aperture: f/2.8, f8
    re.compile(r"\d+(?:\.\d+)?\s?mm"),  # focal length: 50mm
    re.compile(r"iso\s?\d+"),  # ISO 100
    re.compile(r"1/\d+\s?(?:s|sec)?"),  # shutter: 1/250s
    re.compile(r"\d{3,5}\s?[x\u00d7]\s?\d{3,5}"),  # resolution: 6000x4000
    re.compile(r"\d+(?:\.\d+)?\s?(?:mp|fps)"),  # 24mp, 30fps
)


@dataclass(frozen=True, slots=True)
class Keyword:
    index: int  # 1-based position among non-empty keywords (what users count)
    text: str  # stripped original text


def split_keywords(cell: str) -> tuple[list[Keyword], int]:
    """Return (non-empty keywords in order, number of empty items)."""
    items = cell.split(",")
    keywords: list[Keyword] = []
    empty = 0
    for raw in items:
        text = raw.strip()
        if text:
            keywords.append(Keyword(len(keywords) + 1, text))
        else:
            empty += 1
    return keywords, empty


def is_low_value(text: str) -> bool:
    folded = " ".join(text.casefold().split())
    return folded in LOW_VALUE_TERMS or any(p.fullmatch(folded) for p in _LOW_VALUE_PATTERNS)


def check_keywords(ctx: LintContext, row: RowView, cell: str) -> None:
    loc: dict[str, Any] = {
        "line": row.line,
        "row": row.row,
        "column": "Keywords",
        "filename": row.filename or None,
    }
    keywords, empty = split_keywords(cell)
    if not keywords:
        detail = " (only commas or whitespace)" if cell.strip() else ""
        ctx.emit(
            "ADOBE-CSV-KEYWORDS-REQUIRED",
            f"Keywords is empty{detail}.",
            **loc,
            suggestion="Add relevant keywords separated by commas, most important first.",
        )
        return
    if empty and cell.strip():
        ctx.emit(
            "META-KEYWORD-EMPTY-ITEM",
            f"Keywords contains {empty} empty item(s) (consecutive, leading or trailing commas).",
            **loc,
            suggestion="Remove the extra commas (fix rule: drop-empty-keywords).",
        )

    count = len(keywords)
    limit = ctx.registry.int_limit("ADOBE-CSV-KEYWORDS-MAX")
    if count > limit:
        ctx.emit(
            "ADOBE-CSV-KEYWORDS-MAX",
            f"{count} keywords; the CSV limit is {limit}. Keyword order is preserved and nothing "
            "is removed automatically.",
            **loc,
            suggestion=f"Remove the {count - limit} least relevant keyword(s) yourself.",
        )
    guidance = ctx.registry.int_limit("ADOBE-GUIDANCE-KEYWORDS-49")
    if count > guidance:
        ctx.emit(
            "ADOBE-GUIDANCE-KEYWORDS-49",
            f"{count} keywords; Adobe guidance pages mention up to {guidance} per content "
            "submission (advisory; the CSV page allows 50).",
            **loc,
            suggestion="Optional: trim to the most relevant keywords.",
        )

    seen: dict[str, Keyword] = {}
    duplicates: list[tuple[Keyword, Keyword]] = []
    for kw in keywords:
        key = keyword_key(kw.text)
        if key in seen:
            duplicates.append((kw, seen[key]))
        else:
            seen[key] = kw
    if duplicates:
        parts = [
            f'"{excerpt(d.text, 30)}" (#{d.index}) repeats "{excerpt(o.text, 30)}" (#{o.index})'
            for d, o in duplicates
        ]
        ctx.emit(
            "META-KEYWORD-DUPLICATE",
            "Duplicate keywords: " + "; ".join(parts) + ".",
            **loc,
            suggestion="Remove the repeats (fix rule: dedupe-keywords keeps the first occurrence).",
        )

    seen_nfkc: dict[str, Keyword] = {}
    compat: list[tuple[Keyword, Keyword]] = []
    for kw in seen.values():
        key = keyword_key_nfkc(kw.text)
        if key in seen_nfkc:
            compat.append((kw, seen_nfkc[key]))
        else:
            seen_nfkc[key] = kw
    if compat:
        parts = [
            f'"{excerpt(a.text, 30)}" (#{a.index}) equals "{excerpt(b.text, 30)}" (#{b.index})'
            for a, b in compat
        ]
        ctx.emit(
            "META-KEYWORD-DUPLICATE-NFKC",
            "Keywords identical after NFKC normalization: " + "; ".join(parts) + ".",
            **loc,
            suggestion="Keep one form. Originals are never changed automatically.",
        )

    separators: list[str] = []
    for kw in keywords:
        names = [name for ch, name in SUSPICIOUS_KEYWORD_SEPARATORS.items() if ch in kw.text]
        if names:
            separators.append(f'#{kw.index} "{excerpt(kw.text, 30)}" ({", ".join(names)})')
    if separators:
        ctx.emit(
            "META-KEYWORD-SEPARATOR",
            "Keywords contain non-comma separators: " + "; ".join(separators) + ".",
            **loc,
            suggestion="Separate keywords with ASCII commas only.",
        )

    low = [
        f'"{excerpt(kw.text, 30)}" (#{kw.index})' for kw in keywords[:10] if is_low_value(kw.text)
    ]
    if low:
        ctx.emit(
            "META-KEYWORD-LOW-VALUE",
            "Possible technical or filler terms in the first 10 keywords: " + ", ".join(low) + ".",
            **loc,
            suggestion="Heuristic only: consider replacing them with terms that describe the "
            "content.",
        )
