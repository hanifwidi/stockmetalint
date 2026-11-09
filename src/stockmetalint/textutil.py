"""Unicode-aware text helpers.

Length policy (documented in docs/rule-sources.md):

* The primary length of a field is its number of Unicode **code points**
  after UTF-8 decoding, without normalization (``len(str)`` in Python).
* Because browser form ``maxlength`` counts UTF-16 code units, text that is
  within a limit by code points but over it in UTF-16 units (emoji and other
  astral characters) gets a separate advisory.
* Text is never truncated or normalized in place; normalization is only used
  to *compare* values (duplicates) or in explicitly requested fixes.
"""

from __future__ import annotations

import unicodedata

#: Leading characters that spreadsheet applications may treat as a formula.
#: See OWASP "CSV Injection".
FORMULA_PREFIXES: frozenset[str] = frozenset({"=", "+", "-", "@", "\t", "\r"})

#: Bidirectional formatting characters ("Trojan Source", CVE-2021-42574).
BIDI_CONTROLS: frozenset[str] = frozenset(
    {
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)

#: Invisible characters that are suspicious anywhere in metadata.
INVISIBLE_ALWAYS: frozenset[str] = frozenset({"\u200b", "\u2060", "\ufeff", "\u180e", "\u00ad"})

#: Joiners are legitimate inside text (emoji sequences, Indic/Persian scripts)
#: but never needed in a filename.
JOINERS: frozenset[str] = frozenset({"\u200c", "\u200d"})

#: Separators that users commonly type instead of ASCII commas between keywords.
SUSPICIOUS_KEYWORD_SEPARATORS: dict[str, str] = {
    ";": "semicolon",
    "|": "vertical bar",
    "\uff0c": "full-width comma",
    "\u3001": "ideographic comma",
    "\uff1b": "full-width semicolon",
    "\u060c": "Arabic comma",
}


def code_points(text: str) -> int:
    """Primary length measure: Unicode code points."""
    return len(text)


def utf16_units(text: str) -> int:
    """Length in UTF-16 code units (what HTML ``maxlength`` counts)."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def nfc_length(text: str) -> int:
    return len(unicodedata.normalize("NFC", text))


def is_nfc(text: str) -> bool:
    return unicodedata.is_normalized("NFC", text)


def collapse_whitespace(text: str) -> str:
    """Strip and collapse every run of Unicode whitespace to one ASCII space."""
    return " ".join(text.split())


def keyword_key(text: str) -> str:
    """Comparison key for duplicate detection: whitespace-collapsed and casefolded."""
    return collapse_whitespace(text).casefold()


def keyword_key_nfkc(text: str) -> str:
    """Compatibility key (NFKC + casefold), e.g. full-width letters match ASCII."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return collapse_whitespace(unicodedata.normalize("NFKC", folded))


def control_characters(text: str) -> list[str]:
    """Return C0/C1 control characters and line/paragraph separators in *text*."""
    return [ch for ch in text if unicodedata.category(ch) in ("Cc", "Zl", "Zp")]


def invisible_characters(text: str, *, strict: bool) -> list[str]:
    """Bidi controls and invisible characters.

    With ``strict=True`` (filenames) zero-width joiners are reported too.
    """
    found = [ch for ch in text if ch in BIDI_CONTROLS or ch in INVISIBLE_ALWAYS]
    if strict:
        found.extend(ch for ch in text if ch in JOINERS)
    return found


def formula_prefix(text: str) -> str | None:
    """Return the dangerous leading character if *text* could be read as a formula.

    Checks the first character and, for ``= + - @``, the first non-space
    character (some spreadsheet importers trim leading spaces).
    """
    if not text:
        return None
    if text[0] in FORMULA_PREFIXES:
        return text[0]
    stripped = text.lstrip(" ")
    if stripped and stripped[0] in {"=", "+", "-", "@"}:
        return stripped[0]
    return None


def describe_char(ch: str) -> str:
    """Human-readable name, e.g. ``U+202E RIGHT-TO-LEFT OVERRIDE``."""
    name = unicodedata.name(ch, "")
    if not name:
        name = {"\t": "TAB", "\n": "LINE FEED", "\r": "CARRIAGE RETURN"}.get(ch, "CONTROL")
    return f"U+{ord(ch):04X} {name}"


def escape_for_terminal(text: str) -> str:
    """Make untrusted text safe to print: escape control, format and separator chars.

    Prevents terminal escape-sequence injection (e.g. ``\\x1b[2J``) and hides
    nothing: bidi overrides are shown as ``\\u202e`` instead of reordering output.
    """
    out: list[str] = []
    for ch in text:
        if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"):
            code = ord(ch)
            if code <= 0xFF:
                out.append(f"\\x{code:02x}")
            elif code <= 0xFFFF:
                out.append(f"\\u{code:04x}")
            else:
                out.append(f"\\U{code:08x}")
        else:
            out.append(ch)
    return "".join(out)


def excerpt(text: str, limit: int = 60) -> str:
    """Shorten *text* for display in a message (never used to modify data)."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"
