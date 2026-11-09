from __future__ import annotations

import unicodedata

import pytest

from stockmetalint import textutil as t


@pytest.mark.parametrize(
    ("text", "points", "utf16"),
    [
        ("abc", 3, 3),
        ("Pasar tradisional di pagi hari", 30, 30),  # Indonesian
        ("café", 4, 4),                          # precomposed é
        ("café", 5, 5),                         # e + combining acute (NFD)
        ("富士山の朝焼け", 7, 7),  # CJK
        ("sunset \U0001f305", 8, 9),                  # emoji is astral: 2 UTF-16 units
        ("\U0001f468‍\U0001f469‍\U0001f467", 5, 8),  # ZWJ family sequence
    ],
)
def test_length_measures(text: str, points: int, utf16: int) -> None:
    assert t.code_points(text) == points
    assert t.utf16_units(text) == utf16


def test_nfc_length_and_detection() -> None:
    decomposed = "café"
    assert not t.is_nfc(decomposed)
    assert t.nfc_length(decomposed) == 4
    assert t.is_nfc(unicodedata.normalize("NFC", decomposed))


def test_keyword_keys() -> None:
    assert t.keyword_key("  Golden   Hour ") == t.keyword_key("golden hour")
    assert t.keyword_key("Straße") == t.keyword_key("STRASSE")  # casefold, not lower
    assert t.keyword_key("ｃａｔ") != t.keyword_key("cat")  # full-width differs...
    assert t.keyword_key_nfkc("ｃａｔ") == t.keyword_key_nfkc("cat")  # ...until NFKC
    assert t.keyword_key_nfkc("ﬁsh") == t.keyword_key_nfkc("fish")  # ligature


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("=SUM(A1)", "="), ("+1", "+"), ("-2", "-"), ("@cmd", "@"), ("\tx", "\t"), ("\rx", "\r"),
        ("  =evil", "="), ("normal", None), ("", None), ("e=mc2", None), ("a-b", None),
    ],
)
def test_formula_prefix(text: str, expected: str | None) -> None:
    assert t.formula_prefix(text) == expected


def test_control_and_invisible_characters() -> None:
    assert t.control_characters("a\tb\nc ") == ["\t", "\n", " "]
    assert t.invisible_characters("gpj‮.exe", strict=False) == ["‮"]
    assert t.invisible_characters("a‍b", strict=False) == []  # joiner allowed in text
    assert t.invisible_characters("a‍b", strict=True) == ["‍"]  # but not in filenames
    assert t.describe_char("‮") == "U+202E RIGHT-TO-LEFT OVERRIDE"
    assert t.describe_char("\t") == "U+0009 TAB"


def test_escape_for_terminal_neutralizes_escape_sequences() -> None:
    hostile = "ok\x1b[2J\x07‮evil\U000e0001"
    escaped = t.escape_for_terminal(hostile)
    assert "\x1b" not in escaped and "\x07" not in escaped and "‮" not in escaped
    assert escaped == "ok\\x1b[2J\\x07\\u202eevil\\U000e0001"
    assert t.escape_for_terminal("Café 富士 \U0001f305") == "Café 富士 \U0001f305"


def test_excerpt_only_shortens_display() -> None:
    assert t.excerpt("short") == "short"
    long_text = "x" * 100
    assert t.excerpt(long_text, 10) == "x" * 9 + "…"
    assert long_text == "x" * 100  # input untouched
