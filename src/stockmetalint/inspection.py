"""Optional media inspection for ``lint --inspect``.

These are FORMAT checks (does the file look like what its extension says, can
it be decoded) plus a few advisories from Adobe's media requirement pages.
They never judge content, quality or policy compliance. When an optional tool
(Pillow, ffprobe) is missing or fails, the result is reported as INCONCLUSIVE,
never as a pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import warnings
from pathlib import PurePath
from types import ModuleType
from typing import Any

from stockmetalint.asset_inventory import AssetEntry
from stockmetalint.validators.context import LintContext, RowView

HEAD_BYTES = 1024
#: Images above this pixel count are only decoded when JPEG draft scaling applies.
MAX_DECODE_PIXELS = 40_000_000
FFPROBE_TIMEOUT_SECONDS = 30

EXTENSION_KINDS: dict[str, tuple[str, ...]] = {
    ".jpg": ("jpeg",),
    ".jpeg": ("jpeg",),
    ".png": ("png",),
    ".gif": ("gif",),
    ".tif": ("tiff",),
    ".tiff": ("tiff",),
    ".webp": ("webp",),
    ".psd": ("psd",),
    ".eps": ("eps",),
    ".ai": ("pdf", "eps"),
    ".pdf": ("pdf",),
    ".svg": ("svg",),
    ".mp4": ("isobmff",),
    ".mov": ("quicktime", "isobmff"),
}
_QUICKTIME_ATOMS = (b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot")
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov"})
DECODABLE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})


def detect_kind(head: bytes) -> str | None:
    """Identify a file type from its leading bytes."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith((b"%!PS-Adobe", b"\xc5\xd0\xd3\xc6")):
        return "eps"
    if head.startswith(b"8BPS"):
        return "psd"
    if head[4:8] == b"ftyp":
        return "quicktime" if head[8:12] == b"qt  " else "isobmff"
    if head[4:8] in _QUICKTIME_ATOMS:
        return "quicktime"
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<?xml", b"<svg", b"<!--")) and b"<svg" in head.lower():
        return "svg"
    return None


def load_pillow() -> ModuleType | None:
    """Return ``PIL.Image`` if the optional ``images`` extra is installed."""
    try:
        from PIL import Image
    except ImportError:
        return None
    return Image


def find_ffprobe() -> str | None:
    # Pass PATH explicitly so Windows does not search the current directory first.
    return shutil.which("ffprobe", path=os.environ.get("PATH", os.defpath))


def inspect_assets(
    ctx: LintContext,
    matched: list[tuple[RowView, AssetEntry]],
    *,
    image_module: ModuleType | None,
    ffprobe: str | None,
) -> None:
    images_unverified = 0
    videos_unverified = 0
    for row, entry in matched:
        loc: dict[str, Any] = {
            "line": row.line,
            "row": row.row,
            "column": "Filename",
            "filename": entry.name,
        }
        ext = PurePath(entry.name).suffix.lower()
        kinds = EXTENSION_KINDS.get(ext)
        if kinds is None:
            ctx.emit(
                "ASSET-UNSUPPORTED-TYPE",
                f'"{entry.relpath}": extension "{ext or "(none)"}" is not inspectable; matched by '
                "name only.",
                **loc,
            )
            continue
        try:
            with entry.path.open("rb") as handle:
                head = handle.read(HEAD_BYTES)
        except OSError as exc:
            ctx.emit(
                "ASSET-INSPECT-INCONCLUSIVE",
                f'"{entry.relpath}" could not be read for inspection: {exc.strerror or exc}.',
                **loc,
            )
            continue
        detected = detect_kind(head)
        if detected not in kinds:
            ctx.emit(
                "ASSET-SIGNATURE-MISMATCH",
                f'"{entry.relpath}" has extension {ext} but its content looks like '
                f"{detected.upper() if detected else 'unrecognized data'}.",
                **loc,
                suggestion="Re-export the file in the format its extension states.",
            )
            continue
        if ext in DECODABLE_EXTENSIONS:
            if detected == "jpeg":
                _check_jpeg_size(ctx, entry, loc)
            if image_module is None:
                images_unverified += 1
            else:
                _check_image(ctx, entry, loc, image_module, is_jpeg=detected == "jpeg")
        elif ext in VIDEO_EXTENSIONS:
            if ffprobe is None:
                videos_unverified += 1
            else:
                _probe_video(ctx, entry, loc, ffprobe)

    if images_unverified:
        ctx.emit(
            "ASSET-INSPECT-INCONCLUSIVE",
            f"{images_unverified} image file(s) were not decode-checked because Pillow is not "
            "installed.",
            suggestion="pip install 'stockmetalint[images]' to enable image decode checks.",
        )
    if videos_unverified:
        ctx.emit(
            "ASSET-INSPECT-INCONCLUSIVE",
            f"{videos_unverified} video file(s) were not probed because ffprobe was not found on "
            "PATH.",
            suggestion="Install FFmpeg (which provides ffprobe) to enable video checks.",
        )


def _check_jpeg_size(ctx: LintContext, entry: AssetEntry, loc: dict[str, Any]) -> None:
    limit = ctx.registry.int_limit("ADOBE-MEDIA-IMAGE-FILE-SIZE")
    if entry.size is not None and entry.size > limit:
        ctx.emit(
            "ADOBE-MEDIA-IMAGE-FILE-SIZE",
            f'"{entry.relpath}" is {entry.size:,} bytes; the photo guidance limit is {limit:,} bytes.',
            **loc,
            suggestion="Export with higher JPEG compression or smaller dimensions.",
        )


def _check_image(
    ctx: LintContext, entry: AssetEntry, loc: dict[str, Any], image: ModuleType, *, is_jpeg: bool
) -> None:
    bomb_error = getattr(image, "DecompressionBombError", OverflowError)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", getattr(image, "DecompressionBombWarning", RuntimeWarning))
        try:
            with image.open(entry.path) as img:
                width, height = img.size
                progressive = bool(img.info.get("progressive") or img.info.get("progression"))
                if width * height > MAX_DECODE_PIXELS and (not is_jpeg or progressive):
                    ctx.emit(
                        "ASSET-INSPECT-INCONCLUSIVE",
                        f'"{entry.relpath}" is {width}x{height}; too large to decode safely '
                        "(dimension checks only).",
                        **loc,
                    )
                    _megapixel_advisory(ctx, entry, loc, width, height, is_jpeg=is_jpeg)
                    return
                if is_jpeg:
                    # Decode at 1/8 scale: the whole entropy-coded stream is still read
                    # (so truncation/corruption is detected) with ~64x less memory.
                    img.draft("RGB", (max(1, width // 8), max(1, height // 8)))
                img.load()
        except bomb_error:
            ctx.emit(
                "ASSET-INSPECT-INCONCLUSIVE",
                f'"{entry.relpath}" exceeds Pillow\'s decompression-bomb safety limit; not decoded.',
                **loc,
            )
            return
        except Exception as exc:  # noqa: BLE001 - Pillow raises many exception types for bad data
            ctx.emit(
                "ASSET-DECODE-FAILED",
                f'"{entry.relpath}" could not be decoded: {type(exc).__name__}: '
                f"{str(exc).replace(str(entry.path), entry.relpath)}",
                **loc,
                suggestion="Re-export the image; the file is corrupt or truncated.",
            )
            return
    _megapixel_advisory(ctx, entry, loc, width, height, is_jpeg=is_jpeg)


def _megapixel_advisory(
    ctx: LintContext,
    entry: AssetEntry,
    loc: dict[str, Any],
    width: int,
    height: int,
    *,
    is_jpeg: bool,
) -> None:
    if is_jpeg:
        low, high = ctx.registry.range_limit("ADOBE-MEDIA-IMAGE-MEGAPIXELS")
        megapixels = width * height / 1_000_000
        if not low <= megapixels <= high:
            ctx.emit(
                "ADOBE-MEDIA-IMAGE-MEGAPIXELS",
                f'"{entry.relpath}" is {width}x{height} = {megapixels:.2f} MP; the photo guidance '
                f"range is {low:g}-{high:g} MP.",
                **loc,
                suggestion="Check the photo requirements; do not upscale images artificially.",
            )


def _probe_video(ctx: LintContext, entry: AssetEntry, loc: dict[str, Any], ffprobe: str) -> None:
    command = [
        ffprobe,
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        os.fspath(entry.path),
    ]
    try:
        # Fixed argument list, no shell; the path is absolute so it cannot be parsed as an option.
        proc = subprocess.run(  # noqa: S603
            command, capture_output=True, timeout=FFPROBE_TIMEOUT_SECONDS, check=False
        )
    except subprocess.TimeoutExpired:
        ctx.emit(
            "ASSET-INSPECT-INCONCLUSIVE",
            f'ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s on "{entry.relpath}".',
            **loc,
        )
        return
    except OSError as exc:
        ctx.emit(
            "ASSET-INSPECT-INCONCLUSIVE",
            f"ffprobe could not be started: {exc.strerror or exc}.",
            **loc,
        )
        return
    stderr = proc.stderr.decode("utf-8", "replace").replace(os.fspath(entry.path), entry.relpath)
    if proc.returncode != 0:
        first = (
            stderr.strip().splitlines()[0] if stderr.strip() else f"exit status {proc.returncode}"
        )
        ctx.emit(
            "ASSET-VIDEO-UNREADABLE",
            f'ffprobe could not read "{entry.relpath}": {first}',
            **loc,
            suggestion="Re-export the video as MP4 or MOV.",
        )
        return
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except ValueError:
        ctx.emit(
            "ASSET-INSPECT-INCONCLUSIVE",
            f'ffprobe returned unparsable output for "{entry.relpath}".',
            **loc,
        )
        return
    streams = data.get("streams") if isinstance(data, dict) else None
    videos = [s for s in streams or [] if isinstance(s, dict) and s.get("codec_type") == "video"]
    if not videos:
        ctx.emit(
            "ASSET-VIDEO-UNREADABLE",
            f'"{entry.relpath}" has no video stream.',
            **loc,
            suggestion="Re-export the video.",
        )
        return
    codec = str(videos[0].get("codec_name", "unknown"))
    expected = str(ctx.registry.get("ADOBE-MEDIA-VIDEO-CODEC").limit)
    if codec != expected:
        ctx.emit(
            "ADOBE-MEDIA-VIDEO-CODEC",
            f'"{entry.relpath}" uses the {codec} codec; the video guidance names H.264.',
            **loc,
            suggestion="Check Adobe's current video requirements before re-encoding.",
        )
    fmt = data.get("format") if isinstance(data, dict) else None
    raw_duration = fmt.get("duration") if isinstance(fmt, dict) else None
    try:
        duration = float(raw_duration) if isinstance(raw_duration, (str, int, float)) else None
    except ValueError:
        duration = None
    if duration is None:
        ctx.emit(
            "ASSET-INSPECT-INCONCLUSIVE",
            f'ffprobe reported no duration for "{entry.relpath}".',
            **loc,
        )
        return
    low, high = ctx.registry.range_limit("ADOBE-MEDIA-VIDEO-DURATION")
    if not low <= duration <= high:
        ctx.emit(
            "ADOBE-MEDIA-VIDEO-DURATION",
            f'"{entry.relpath}" is {duration:.2f} s long; the guidance range is {low:g}-{high:g} s.',
            **loc,
            suggestion="Trim or extend the clip to fit the documented range.",
        )
