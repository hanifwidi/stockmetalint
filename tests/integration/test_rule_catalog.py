"""Every rule in the registry must be triggerable by a minimal synthetic input.

Adding a rule without a trigger here fails ``test_catalog_covers_every_rule``,
and a trigger that stops firing fails its parametrized case.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest

from stockmetalint.rules.registry import load_registry
from tests.conftest import codes, csv_bytes, lint, make_row, unique_rows

Trigger = Callable[[Path], list[str]]


def _rows(*rows: list[str], **opts: object) -> list[str]:
    return codes(lint(csv_bytes(list(rows)), **opts))


def _header(header: list[str]) -> list[str]:
    return codes(
        lint(csv_bytes([["a.jpg", "Title", "a, b, c", "1", ""][: len(header)]], header=header))
    )


def _assets(
    tmp: Path, files: dict[str, bytes | None], *rows: list[str], **opts: object
) -> list[str]:
    root = tmp / "assets"
    root.mkdir(exist_ok=True)
    for name, content in files.items():
        if content is None:
            (root / name).mkdir()
        else:
            (root / name).write_bytes(content)
    return codes(lint(csv_bytes(list(rows)), assets_dir=root, **opts))


def _jpeg(size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size).save(buffer, "JPEG")
    return buffer.getvalue()


def _video(tmp: Path, codec: str, seconds: int) -> bytes:
    path = tmp / f"v-{codec}.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=s=32x32:d={seconds}",
            "-c:v",
            codec,
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    return path.read_bytes()


def _symlink(tmp: Path, target_outside: bool) -> list[str]:
    root = tmp / "assets"
    root.mkdir()
    outside = tmp / "secret.jpg"
    outside.write_bytes(b"x")
    os.symlink(outside if target_outside else tmp / "missing.jpg", root / "link.jpg")
    return codes(lint(csv_bytes([make_row("link.jpg")]), assets_dir=root))


def _sparse_jpeg(tmp: Path) -> list[str]:
    root = tmp / "assets"
    root.mkdir()
    with (root / "photo-001.jpg").open("wb") as handle:
        handle.write(b"\xff\xd8\xff\xe0")
        handle.truncate(45_000_001)  # sparse: no 45 MB of real writes
    return codes(lint(csv_bytes([make_row()]), assets_dir=root, inspect=True))


def _releases(tmp: Path) -> list[str]:
    root = tmp / "releases"
    root.mkdir()
    return codes(lint(csv_bytes([make_row(releases="model-a")]), releases_dir=root))


TRIGGERS: dict[str, Trigger] = {
    "CSV-FILE-EMPTY": lambda t: codes(lint(b"")),
    "CSV-FILE-BINARY": lambda t: codes(lint(b"PK\x03\x04xlsx")),
    "CSV-NUL-BYTE": lambda t: codes(lint(b"a\x00b\n")),
    "CSV-ENCODING-BOM": lambda t: codes(lint(csv_bytes([make_row()], bom=True))),
    "CSV-MALFORMED": lambda t: codes(lint(b'Filename,Title,Keywords\na.jpg,"x\n')),
    "CSV-ROW-FIELD-COUNT": lambda t: codes(
        lint(b"Filename,Title,Keywords,Category,Releases\na,b\n")
    ),
    "CSV-BLANK-ROW": lambda t: codes(lint(csv_bytes([make_row()]) + b",,,,\n")),
    "META-WHITESPACE": lambda t: _rows(make_row(title=" T ")),
    "META-CONTROL-CHAR": lambda t: _rows(make_row(title="a\tb")),
    "META-UNICODE-NFC": lambda t: _rows(make_row(title="Café")),
    "META-LENGTH-UTF16": lambda t: _rows(make_row(title="\U0001f305" * 40)),
    "META-FILENAME-PORTABILITY": lambda t: _rows(make_row(filename="a?.jpg")),
    "META-KEYWORD-DUPLICATE": lambda t: _rows(make_row(keywords="a, A, b")),
    "META-KEYWORD-DUPLICATE-NFKC": lambda t: _rows(make_row(keywords="a, ａ, b")),
    "META-KEYWORD-EMPTY-ITEM": lambda t: _rows(make_row(keywords="a,,b")),
    "META-KEYWORD-SEPARATOR": lambda t: _rows(make_row(keywords="a; b")),
    "META-KEYWORD-LOW-VALUE": lambda t: _rows(make_row(keywords="sea, jpg")),
    "BATCH-FILENAME-DUPLICATE": lambda t: _rows(make_row(), make_row(title="Other title")),
    "BATCH-FILENAME-CASE-COLLISION": lambda t: _rows(make_row("a.jpg"), make_row("A.jpg", "Other")),
    "BATCH-FILENAME-UNICODE-COLLISION": lambda t: _rows(
        make_row("é.jpg"), make_row("é.jpg", "Other")
    ),
    "BATCH-TITLE-DUPLICATE": lambda t: _rows(
        make_row("a.jpg"), make_row("b.jpg", keywords="x, y, z")
    ),
    "BATCH-KEYWORDS-IDENTICAL": lambda t: _rows(
        make_row("a.jpg"), make_row("b.jpg", "Other title")
    ),
    "BATCH-KEYWORDS-NEAR-DUPLICATE": lambda t: _rows(
        make_row("a.jpg", keywords=", ".join("abcdefghij") + ", k"),
        make_row("b.jpg", "Other", ", ".join("abcdefghij") + ", z"),
    ),
    "SEC-FORMULA-PREFIX": lambda t: _rows(make_row(title="=1+1")),
    "SEC-INVISIBLE-CHAR": lambda t: _rows(make_row(title="a‮b")),
    "ASSET-MISSING": lambda t: _assets(t, {}, make_row()),
    "ASSET-CASE-MISMATCH": lambda t: _assets(t, {"PHOTO-001.JPG": b"x"}, make_row()),
    "ASSET-UNICODE-MISMATCH": lambda t: _assets(t, {"é.jpg": b"x"}, make_row("é.jpg")),
    "ASSET-ORPHAN": lambda t: _assets(t, {"photo-001.jpg": b"x", "extra.jpg": b"x"}, make_row()),
    "ASSET-DIR-EMPTY": lambda t: _assets(t, {}, make_row()),
    "ASSET-CASE-COLLISION": lambda t: _assets(t, {"x.jpg": b"1", "X.jpg": b"2"}, make_row("x.jpg")),
    "ASSET-AMBIGUOUS": lambda t: (
        (t / "assets" / "s1").mkdir(parents=True),
        (t / "assets" / "s2").mkdir(),
        (t / "assets" / "s1" / "photo-001.jpg").write_bytes(b"x"),
        (t / "assets" / "s2" / "photo-001.jpg").write_bytes(b"x"),
        codes(lint(csv_bytes([make_row()]), assets_dir=t / "assets", recursive=True)),
    )[-1],
    "ASSET-SYMLINK-ESCAPE": lambda t: _symlink(t, True),
    "ASSET-SYMLINK-BROKEN": lambda t: _symlink(t, False),
    "ASSET-NOT-REGULAR-FILE": lambda t: _assets(t, {"photo-001.jpg": None}, make_row()),
    "ASSET-EMPTY-FILE": lambda t: _assets(t, {"photo-001.jpg": b""}, make_row()),
    "ASSET-RELEASE-MISSING": _releases,
    "ASSET-SIGNATURE-MISMATCH": lambda t: _assets(
        t, {"photo-001.jpg": b"\x89PNG\r\n\x1a\n"}, make_row(), inspect=True
    ),
    "ASSET-UNSUPPORTED-TYPE": lambda t: _assets(
        t, {"a.txt": b"x"}, make_row("a.txt"), inspect=True
    ),
    "ASSET-DECODE-FAILED": lambda t: _assets(
        t, {"photo-001.jpg": _jpeg((64, 64))[:200]}, make_row(), inspect=True
    ),
    "ASSET-VIDEO-UNREADABLE": lambda t: _assets(
        t, {"c.mp4": b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 9}, make_row("c.mp4"), inspect=True
    ),
    # Run with ffprobe forced unavailable (see the test below): a real code path, not a stub.
    "ASSET-INSPECT-INCONCLUSIVE": lambda t: _assets(
        t, {"c.mp4": b"\x00\x00\x00\x18ftypmp42"}, make_row("c.mp4"), inspect=True
    ),
    "ADOBE-CSV-FILE-TYPE": lambda t: codes(lint(csv_bytes([make_row()]), source_name="a.xlsx")),
    "ADOBE-CSV-FILE-SIZE": lambda t: codes(lint(csv_bytes(unique_rows(4000)) + b"\n" * 900_000)),
    "ADOBE-CSV-FILE-SIZE-DECIMAL": lambda t: codes(
        lint(csv_bytes(unique_rows(10)) + b"\n" * 1_000_000)
    ),
    "ADOBE-CSV-ROW-LIMIT": lambda t: codes(lint(csv_bytes(unique_rows(5001)))),
    "ADOBE-CSV-ENCODING-UTF8": lambda t: codes(lint(b"Filename\n\xe9\n")),
    "ADOBE-CSV-HEADER-ABSENT": lambda t: codes(lint(csv_bytes([make_row()], header=None))),
    "ADOBE-CSV-HEADER-REQUIRED": lambda t: _header(["Filename", "Title"]),
    "ADOBE-CSV-HEADER-NAME": lambda t: _header(
        ["filename", "Title", "Keywords", "Category", "Releases"]
    ),
    "ADOBE-CSV-HEADER-UNKNOWN": lambda t: _header(["Filename", "Title", "Keywords", "Notes"]),
    "ADOBE-CSV-HEADER-DUPLICATE": lambda t: _header(["Filename", "Title", "Title"]),
    "ADOBE-CSV-HEADER-OPTIONAL-MISSING": lambda t: _header(["Filename", "Title", "Keywords"]),
    "ADOBE-CSV-HEADER-ORDER": lambda t: _header(
        ["Title", "Filename", "Keywords", "Category", "Releases"]
    ),
    "ADOBE-CSV-FILENAME-REQUIRED": lambda t: _rows(make_row(filename="")),
    "ADOBE-CSV-FILENAME-LENGTH": lambda t: _rows(make_row(filename="a" * 27 + ".jpg")),
    "ADOBE-CSV-FILENAME-EXTENSION": lambda t: _rows(make_row(filename="photo")),
    "ADOBE-CSV-FILENAME-PATH": lambda t: _rows(make_row(filename="../a.jpg")),
    "ADOBE-CSV-TITLE-REQUIRED": lambda t: _rows(make_row(title="")),
    "ADOBE-CSV-TITLE-LENGTH": lambda t: _rows(make_row(title="x" * 71)),
    "ADOBE-CSV-TITLE-COMMA": lambda t: _rows(make_row(title="Sea, sky")),
    "ADOBE-CSV-KEYWORDS-REQUIRED": lambda t: _rows(make_row(keywords="")),
    "ADOBE-CSV-KEYWORDS-MAX": lambda t: _rows(
        make_row(keywords=",".join(f"k{i}" for i in range(51)))
    ),
    "ADOBE-CSV-CATEGORY-FORMAT": lambda t: _rows(make_row(category="x")),
    "ADOBE-CSV-CATEGORY-UNKNOWN": lambda t: _rows(make_row(category="99")),
    "ADOBE-CSV-CATEGORY-RECOMMENDED": lambda t: _rows(make_row(category="")),
    "ADOBE-CSV-RELEASE-NAME-LENGTH": lambda t: _rows(make_row(releases="r" * 31)),
    "ADOBE-GUIDANCE-KEYWORDS-49": lambda t: _rows(
        make_row(keywords=",".join(f"k{i}" for i in range(50))), profile="editorial"
    ),
    "ADOBE-MEDIA-IMAGE-MEGAPIXELS": lambda t: _assets(
        t, {"photo-001.jpg": _jpeg()}, make_row(), inspect=True
    ),
    "ADOBE-MEDIA-IMAGE-FILE-SIZE": lambda t: _sparse_jpeg(t),
    "ADOBE-MEDIA-VIDEO-CODEC": lambda t: _assets(
        t, {"c.mp4": _video(t, "mpeg4", 6)}, make_row("c.mp4"), inspect=True
    ),
    "ADOBE-MEDIA-VIDEO-DURATION": lambda t: _assets(
        t, {"c.mp4": _video(t, "libx264", 2)}, make_row("c.mp4"), inspect=True
    ),
}

NEEDS_FFMPEG = {"ADOBE-MEDIA-VIDEO-CODEC", "ADOBE-MEDIA-VIDEO-DURATION", "ASSET-VIDEO-UNREADABLE"}
NEEDS_SYMLINKS = {"ASSET-SYMLINK-ESCAPE", "ASSET-SYMLINK-BROKEN"}
NEEDS_CASE_SENSITIVE_FS = {"ASSET-CASE-COLLISION"}


def test_catalog_covers_every_rule() -> None:
    assert set(TRIGGERS) == set(load_registry().rules)


@pytest.mark.parametrize("rule_id", sorted(TRIGGERS))
def test_rule_is_triggerable(rule_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if rule_id in NEEDS_FFMPEG and not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not installed")
    if rule_id in NEEDS_SYMLINKS and sys.platform == "win32":
        pytest.skip("symlinks need privileges on Windows")
    if rule_id in NEEDS_CASE_SENSITIVE_FS and sys.platform in ("win32", "darwin"):
        pytest.skip("needs a case-sensitive file system")
    pytest.importorskip("PIL")
    if rule_id == "ASSET-INSPECT-INCONCLUSIVE":
        monkeypatch.setattr("stockmetalint.engine.find_ffprobe", lambda: None)
    found = TRIGGERS[rule_id](tmp_path)
    assert rule_id in found
