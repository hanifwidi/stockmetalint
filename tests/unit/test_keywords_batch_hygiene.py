from __future__ import annotations

from stockmetalint.validators.keywords import is_low_value, split_keywords
from tests.conftest import codes, csv_bytes, lint, make_row


def test_split_keywords_preserves_order_and_counts_empty_items() -> None:
    keywords, empty = split_keywords(" sky , sun,, sea ,")
    assert [(k.index, k.text) for k in keywords] == [(1, "sky"), (2, "sun"), (3, "sea")]
    assert empty == 2


def test_duplicate_keywords_case_whitespace_and_order_preserved_in_message() -> None:
    report = lint(csv_bytes([make_row(keywords="Beach, sun,  beach , BEACH, sea")]))
    dup = [d for d in report.diagnostics if d.code == "META-KEYWORD-DUPLICATE"]
    assert len(dup) == 1
    assert dup[0].message == (
        'Duplicate keywords: "beach" (#3) repeats "Beach" (#1); "BEACH" (#4) repeats "Beach" (#1).'
    )


def test_nfkc_duplicates_are_suggestions_only() -> None:
    report = lint(csv_bytes([make_row(keywords="cat, \uff43\uff41\uff54, dog, bird")]))
    nfkc = [d for d in report.diagnostics if d.code == "META-KEYWORD-DUPLICATE-NFKC"]
    assert len(nfkc) == 1 and nfkc[0].severity.value == "info"
    assert "META-KEYWORD-DUPLICATE" not in codes(report)


def test_casefold_handles_ligatures_as_plain_duplicates() -> None:
    # Full Unicode case folding maps U+FB01 (fi ligature) to "fi".
    report = lint(csv_bytes([make_row(keywords="\ufb01sh, fish, sea")]))
    assert "META-KEYWORD-DUPLICATE" in codes(report)


def test_empty_items_separators_and_low_value() -> None:
    rows = [
        make_row(keywords="sky,,sun, sea,"),
        make_row(filename="b.jpg", keywords="猫，犬, cat; dog, a|b, x"),
        make_row(filename="c.jpg", keywords="beach, jpg, 4K, f/2.8, 50mm, ISO 100, sea"),
    ]
    report = lint(csv_bytes(rows))
    found = codes(report)
    assert "META-KEYWORD-EMPTY-ITEM" in found
    sep = next(d for d in report.diagnostics if d.code == "META-KEYWORD-SEPARATOR")
    assert "full-width comma" in sep.message and "semicolon" in sep.message
    low = next(d for d in report.diagnostics if d.code == "META-KEYWORD-LOW-VALUE")
    for term in ("jpg", "4K", "f/2.8", "50mm", "ISO 100"):
        assert f'"{term}"' in low.message


def test_low_value_heuristic_only_checks_first_ten() -> None:
    keywords = ", ".join([f"word{i}" for i in range(10)] + ["jpg"])
    assert "META-KEYWORD-LOW-VALUE" not in codes(lint(csv_bytes([make_row(keywords=keywords)])))
    assert is_low_value("Royalty  Free") and not is_low_value("photography")


def test_only_commas_is_required_error() -> None:
    report = lint(csv_bytes([make_row(keywords=" , ,")]))
    assert "ADOBE-CSV-KEYWORDS-REQUIRED" in codes(report)
    assert "META-KEYWORD-EMPTY-ITEM" not in codes(report)


def test_batch_filename_duplicates_and_collisions() -> None:
    rows = [
        make_row("a.jpg", "Title one here", "a1, b1, c1"),
        make_row("a.jpg", "Title two here", "a2, b2, c2"),
        make_row("A.JPG", "Title three here", "a3, b3, c3"),
        make_row("café.jpg", "Title four here", "a4, b4, c4"),
        make_row("café.jpg", "Title five here", "a5, b5, c5"),
    ]
    report = lint(csv_bytes(rows))
    by_code = {d.code: d for d in report.diagnostics}
    assert by_code["BATCH-FILENAME-DUPLICATE"].row == 2
    assert by_code["BATCH-FILENAME-CASE-COLLISION"].row == 3
    assert by_code["BATCH-FILENAME-UNICODE-COLLISION"].row == 5
    assert report.exit_code() == 1  # duplicate filename is blocking


def test_batch_titles_and_keyword_sets_are_review_warnings() -> None:
    top10 = ", ".join(f"k{i}" for i in range(10))
    rows = [
        make_row("a.jpg", "Same title", "x, y, z"),
        make_row("b.jpg", "same  TITLE", "z, Y, x"),
        make_row("c.jpg", "Other", top10 + ", extra1"),
        make_row("d.jpg", "Another", top10 + ", extra2"),
        make_row("e.jpg", "Short", "p, q"),
        make_row("f.jpg", "Short too", "p, q"),
    ]
    report = lint(csv_bytes(rows))
    found = {d.code: d for d in report.diagnostics}
    assert found["BATCH-TITLE-DUPLICATE"].row == 2
    assert found["BATCH-KEYWORDS-IDENTICAL"].row == 2  # order-insensitive set
    assert found["BATCH-KEYWORDS-NEAR-DUPLICATE"].row == 4
    assert codes(report).count("BATCH-KEYWORDS-IDENTICAL") == 1  # 2-keyword sets are ignored
    assert report.exit_code() == 0  # review warnings never block


def test_hygiene_checks() -> None:
    rows = [
        make_row(" a.jpg", " Padded title ", "a, b, c", "11", ""),
        make_row("b.jpg", "Line\nbreak", "a, b, c"),
        make_row("gpj‮.jpg", "Hidden​space", "a, b, c"),
        make_row("c.jpg", "Café at night", "a, b, c"),
        make_row("d.jpg", "@mention title", "-minus, b, c", "+1"),
    ]
    report = lint(csv_bytes(rows))
    found = codes(report)
    assert found.count("META-WHITESPACE") == 2
    assert "META-CONTROL-CHAR" in found
    assert found.count("SEC-INVISIBLE-CHAR") == 2
    assert "META-UNICODE-NFC" in found
    assert found.count("SEC-FORMULA-PREFIX") == 3
