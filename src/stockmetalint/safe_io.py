"""Output safety: never overwrite inputs, write atomically, leave no partial files."""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import tempfile
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from stockmetalint.errors import OutputError


def _same_path_text(a: Path, b: Path) -> bool:
    if a == b or os.path.normcase(a) == os.path.normcase(b):
        return True
    if sys.platform in ("darwin", "win32"):
        # Default file systems on macOS and Windows are case-insensitive (and
        # macOS normalizes Unicode), so compare loosely there.
        def fold(p: Path) -> str:
            return unicodedata.normalize("NFC", str(p)).casefold()

        return fold(a) == fold(b)
    return False


def check_output_path(output: Path, *, protected: Sequence[Path], overwrite: bool) -> None:
    """Refuse outputs that alias a protected input (directly, via symlink, hard link or case)."""
    if output.is_symlink():
        raise OutputError(f"output path is a symbolic link; refusing to write through it: {output}")
    if output.exists():
        if output.is_dir():
            raise OutputError(f"output path is a directory: {output}")
        for item in protected:
            with contextlib.suppress(OSError):
                if item.exists() and item.samefile(output):
                    raise OutputError(f"output path is the same file as the input: {output}")
        if not overwrite:
            raise OutputError(
                f"output file already exists: {output} (pass --overwrite to replace it)"
            )
    target = output.resolve(strict=False)
    for item in protected:
        if _same_path_text(target, item.resolve(strict=False)):
            raise OutputError(f"output path refers to the input file: {output}")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temporary file in the same directory, fsync, then rename into place.

    On any failure the temporary file is removed and an existing *path* is left
    untouched. New files are created with owner-only permissions (0600 on POSIX).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        raise OutputError(f"cannot create output in {path.parent}: {exc.strerror or exc}") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    except BaseException as exc:
        with contextlib.suppress(OSError):
            Path(tmp_name).unlink()
        if isinstance(exc, OSError):
            raise OutputError(f"cannot write {path}: {exc.strerror or exc}") from None
        raise


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
