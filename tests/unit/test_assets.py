from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from stockmetalint import inspection
from stockmetalint.asset_inventory import EntryKind, scan_assets
from stockmetalint.errors import InputError
from tests.conftest import codes, csv_bytes, lint, make_row

needs_symlinks = pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks need privileges on Windows"
)


def jpeg_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buffer, "JPEG")
    return buffer.getvalue()


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    root.mkdir()
    return root


def rows_for(*names: str) -> bytes:
    return csv_bytes(
        [make_row(n, f"Title for asset {i}", f"a{i}, b{i}, c{i}") for i, n in enumerate(names)]
    )


def test_exact_match_case_unicode_missing_and_orphans(assets: Path) -> None:
    for name in ("match.jpg", "lower.jpg", "café.jpg", "orphan.jpg", ".DS_Store", "Thumbs.db"):
        (assets / name).write_bytes(b"data")
    report = lint(
        rows_for("match.jpg", "LOWER.jpg", "café.jpg", "missing.jpg", " match.jpg "),
        assets_dir=assets,
    )
    by_code = {}
    for d in report.diagnostics:
        by_code.setdefault(d.code, []).append(d)
    assert [d.row for d in by_code["ASSET-CASE-MISMATCH"]] == [2]
    assert [d.row for d in by_code["ASSET-UNICODE-MISMATCH"]] == [3]
    missing = by_code["ASSET-MISSING"]
    assert [d.row for d in missing] == [4, 5]
    assert "whitespace" in missing[1].message
    assert [d.filename for d in by_code["ASSET-ORPHAN"]] == ["orphan.jpg"]  # hidden/system ignored
    assert report.assets_checked


def test_missing_suggests_close_match(assets: Path) -> None:
    (assets / "sunset-001.jpg").write_bytes(b"x")
    report = lint(rows_for("sunset-01.jpg"), assets_dir=assets)
    missing = next(d for d in report.diagnostics if d.code == "ASSET-MISSING")
    assert 'Closest file: "sunset-001.jpg"' in missing.message


def test_empty_directory_and_zero_byte_and_directory_entries(assets: Path) -> None:
    report = lint(rows_for("a.jpg"), assets_dir=assets)
    assert {"ASSET-DIR-EMPTY", "ASSET-MISSING"} <= set(codes(report))
    (assets / "empty.jpg").write_bytes(b"")
    (assets / "folder.jpg").mkdir()
    found = codes(lint(rows_for("empty.jpg", "folder.jpg"), assets_dir=assets))
    assert "ASSET-EMPTY-FILE" in found and "ASSET-NOT-REGULAR-FILE" in found


def test_path_like_filenames_are_not_matched(assets: Path) -> None:
    (assets / "raw.jpg").write_bytes(b"x")
    report = lint(rows_for("../raw.jpg"), assets_dir=assets)
    assert "ADOBE-CSV-FILENAME-PATH" in codes(report)
    assert "ASSET-MISSING" not in codes(report)
    assert "ASSET-ORPHAN" in codes(report)


@needs_symlinks
def test_symlink_escape_and_broken_links_are_not_followed(tmp_path: Path, assets: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(jpeg_bytes())
    (assets / "inside.jpg").write_bytes(jpeg_bytes())
    os.symlink(outside / "secret.jpg", assets / "escape.jpg")
    os.symlink(assets / "inside.jpg", assets / "alias.jpg")
    os.symlink(tmp_path / "nowhere.jpg", assets / "broken.jpg")
    os.symlink(outside, assets / "linked-dir")
    report = lint(
        rows_for("escape.jpg", "alias.jpg", "broken.jpg", "inside.jpg"),
        assets_dir=assets,
        recursive=True,
        inspect=True,
    )
    found = codes(report)
    assert "ASSET-SYMLINK-ESCAPE" in found and "ASSET-SYMLINK-BROKEN" in found
    inventory = scan_assets(assets, recursive=True)
    kinds = {e.name: e.kind for e in inventory.entries}
    assert kinds["linked-dir"] is EntryKind.SYMLINK_ESCAPE  # never descended into
    assert kinds["alias.jpg"] is EntryKind.FILE
    assert not any(e.relpath.startswith("linked-dir/") for e in inventory.entries)


def test_recursive_scan_and_ambiguity(assets: Path) -> None:
    (assets / "a").mkdir()
    (assets / "b").mkdir()
    (assets / "a" / "dup.jpg").write_bytes(b"x")
    (assets / "b" / "dup.jpg").write_bytes(b"x")
    flat = lint(rows_for("dup.jpg"), assets_dir=assets)
    assert "ASSET-MISSING" in codes(flat)  # subdirectories ignored without --recursive
    deep = lint(rows_for("dup.jpg"), assets_dir=assets, recursive=True)
    assert "ASSET-AMBIGUOUS" in codes(deep) and "ASSET-ORPHAN" not in codes(deep)


@pytest.mark.skipif(
    sys.platform in ("win32", "darwin"), reason="needs a case-sensitive file system"
)
def test_case_collision_between_files(assets: Path) -> None:
    (assets / "x.jpg").write_bytes(b"1")
    (assets / "X.jpg").write_bytes(b"2")
    assert "ASSET-CASE-COLLISION" in codes(lint(rows_for("x.jpg"), assets_dir=assets))


def test_unicode_and_space_paths(tmp_path: Path) -> None:
    root = tmp_path / "fötos 写真"
    root.mkdir()
    (root / "富士山.jpg").write_bytes(b"x")
    assert codes(lint(rows_for("富士山.jpg"), assets_dir=root)) == []


def test_bad_asset_dir_is_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="not found"):
        scan_assets(tmp_path / "nope")
    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    with pytest.raises(InputError, match="not a directory"):
        scan_assets(file_path)


def test_entry_cap(monkeypatch: pytest.MonkeyPatch, assets: Path) -> None:
    import stockmetalint.asset_inventory as inv

    for i in range(3):
        (assets / f"{i}.jpg").write_bytes(b"x")
    monkeypatch.setattr(inv, "MAX_ENTRIES", 2)
    with pytest.raises(InputError, match="more than 2 entries"):
        inv.scan_assets(assets)


def test_releases_directory(tmp_path: Path) -> None:
    rel = tmp_path / "releases"
    rel.mkdir()
    (rel / "model-a.jpg").write_bytes(b"x")
    (rel / "property-b").write_bytes(b"x")
    data = csv_bytes([make_row(releases="model-a, property-b, missing-c, ../evil")])
    report = lint(data, releases_dir=rel)
    missing = [d for d in report.diagnostics if d.code == "ASSET-RELEASE-MISSING"]
    messages = sorted(d.message for d in missing)
    assert len(missing) == 2
    assert "not a bare file name" in messages[0] and "missing-c" in messages[1]


# --------------------------------------------------------------------------- inspection


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (PNG_SIGNATURE, "png"),
        (b"GIF89a", "gif"),
        (b"II*\x00", "tiff"),
        (b"RIFF\x00\x00\x00\x00WEBP", "webp"),
        (b"%PDF-1.7", "pdf"),
        (b"%!PS-Adobe-3.0", "eps"),
        (b"8BPS", "psd"),
        (b"\x00\x00\x00\x18ftypmp42", "isobmff"),
        (b"\x00\x00\x00\x14ftypqt  ", "quicktime"),
        (b"\x00\x00\x00\x08wide", "quicktime"),
        (b'<?xml version="1.0"?><svg>', "svg"),
        (b"hello", None),
    ],
)
def test_detect_kind(head: bytes, kind: str | None) -> None:
    assert inspection.detect_kind(head) == kind


def test_inspect_signature_decode_and_megapixels(assets: Path) -> None:
    pytest.importorskip("PIL")
    (assets / "good.jpg").write_bytes(jpeg_bytes())
    (assets / "fake.jpg").write_bytes(PNG_SIGNATURE)
    good = jpeg_bytes((64, 64))
    (assets / "truncated.jpg").write_bytes(good[: len(good) // 2])
    (assets / "notes.txt").write_bytes(b"text")
    report = lint(
        rows_for("good.jpg", "fake.jpg", "truncated.jpg", "notes.txt"),
        assets_dir=assets,
        inspect=True,
    )
    found = {d.code: d for d in report.diagnostics}
    assert (
        found["ASSET-SIGNATURE-MISMATCH"].row == 2
        and "PNG" in found["ASSET-SIGNATURE-MISMATCH"].message
    )
    assert found["ASSET-DECODE-FAILED"].row == 3
    assert found["ASSET-UNSUPPORTED-TYPE"].row == 4
    assert found["ADOBE-MEDIA-IMAGE-MEGAPIXELS"].row == 1  # 8x8 is far below 4 MP
    assert report.media_inspected


def test_inspect_without_pillow_is_inconclusive_not_pass(
    monkeypatch: pytest.MonkeyPatch, assets: Path
) -> None:
    monkeypatch.setattr(inspection, "load_pillow", lambda: None)
    import stockmetalint.engine as engine

    monkeypatch.setattr(engine, "load_pillow", lambda: None)
    (assets / "good.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    report = lint(rows_for("good.jpg"), assets_dir=assets, inspect=True)
    inconclusive = [d for d in report.diagnostics if d.code == "ASSET-INSPECT-INCONCLUSIVE"]
    assert len(inconclusive) == 1 and "Pillow is not installed" in inconclusive[0].message


def test_inspect_large_jpeg_file_size_advisory(
    monkeypatch: pytest.MonkeyPatch, assets: Path
) -> None:
    import stockmetalint.engine as engine

    monkeypatch.setattr(engine, "load_pillow", lambda: None)
    big = assets / "big.jpg"
    with big.open("wb") as handle:
        handle.write(b"\xff\xd8\xff\xe0")
        handle.truncate(45_000_001)  # sparse file: no 45 MB of real writes
    assert "ADOBE-MEDIA-IMAGE-FILE-SIZE" in codes(
        lint(rows_for("big.jpg"), assets_dir=assets, inspect=True)
    )


def test_inspect_without_ffprobe_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch, assets: Path
) -> None:
    import stockmetalint.engine as engine

    monkeypatch.setattr(engine, "find_ffprobe", lambda: None)
    (assets / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16)
    report = lint(rows_for("clip.mp4"), assets_dir=assets, inspect=True)
    assert [d.message for d in report.diagnostics if d.code == "ASSET-INSPECT-INCONCLUSIVE"] == [
        "1 video file(s) were not probed because ffprobe was not found on PATH."
    ]


FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(
    not FFMPEG or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe not installed"
)


def _make_video(path: Path, codec: str, seconds: float) -> None:
    assert FFMPEG is not None
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=64x64:d={seconds}",
            "-c:v",
            codec,
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )


@needs_ffmpeg
def test_ffprobe_codec_duration_and_unreadable(assets: Path) -> None:
    _make_video(assets / "ok.mp4", "libx264", 6)
    _make_video(assets / "mpeg4.mp4", "mpeg4", 1)
    (assets / "broken.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40)
    report = lint(rows_for("ok.mp4", "mpeg4.mp4", "broken.mp4"), assets_dir=assets, inspect=True)
    rows = {(d.code, d.row) for d in report.diagnostics}
    assert ("ADOBE-MEDIA-VIDEO-CODEC", 2) in rows
    assert ("ADOBE-MEDIA-VIDEO-DURATION", 2) in rows
    assert ("ASSET-VIDEO-UNREADABLE", 3) in rows
    assert not [d for d in report.diagnostics if d.row == 1]


def test_ffprobe_failures_are_inconclusive(monkeypatch: pytest.MonkeyPatch, assets: Path) -> None:
    from stockmetalint.asset_inventory import AssetEntry
    from stockmetalint.rules.registry import load_registry
    from stockmetalint.validators.context import LintContext

    entry = AssetEntry("c.mp4", "c.mp4", assets / "c.mp4", EntryKind.FILE, 10)
    ctx = LintContext(load_registry())

    def timeout(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)

    monkeypatch.setattr(inspection.subprocess, "run", timeout)
    inspection._probe_video(ctx, entry, {"filename": "c.mp4"}, "/usr/bin/ffprobe")

    class Proc:
        returncode = 0
        stdout = b"not json"
        stderr = b""

    monkeypatch.setattr(inspection.subprocess, "run", lambda *a, **k: Proc())
    inspection._probe_video(ctx, entry, {"filename": "c.mp4"}, "/usr/bin/ffprobe")
    Proc.stdout = b'{"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}}'
    inspection._probe_video(ctx, entry, {"filename": "c.mp4"}, "/usr/bin/ffprobe")
    assert [d.code for d in ctx.diagnostics] == ["ASSET-INSPECT-INCONCLUSIVE"] * 3
