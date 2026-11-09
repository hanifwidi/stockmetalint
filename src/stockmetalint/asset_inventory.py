"""Local asset inventory and filename matching.

Safety properties:

* Only directory entries are listed (``os.scandir``); no file contents are read.
* Symbolic links are resolved only to classify them. A link whose target is
  outside the asset root is reported and never followed or read.
* Symlinked directories are never descended into, even with ``--recursive``.
* Entry count and recursion depth are capped.
"""

from __future__ import annotations

import difflib
import enum
import os
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from stockmetalint.errors import InputError
from stockmetalint.textutil import excerpt
from stockmetalint.validators.adobe import path_problem
from stockmetalint.validators.context import LintContext, RowView

IGNORED_NAMES = frozenset({"thumbs.db", "desktop.ini", "ehthumbs.db"})
MAX_ENTRIES = 200_000
MAX_DEPTH = 32
RELEASE_EXTENSIONS = (".jpg", ".jpeg")


class EntryKind(enum.Enum):
    FILE = "file"
    DIRECTORY = "directory"
    SPECIAL = "special"
    SYMLINK_ESCAPE = "symlink-escape"
    SYMLINK_BROKEN = "symlink-broken"


@dataclass(frozen=True, slots=True)
class AssetEntry:
    name: str
    relpath: str
    path: Path
    kind: EntryKind
    size: int | None


@dataclass(frozen=True, slots=True)
class AssetInventory:
    entries: tuple[AssetEntry, ...]
    ignored: int
    skipped_subdirectories: int

    @property
    def files(self) -> list[AssetEntry]:
        """Candidate media entries (everything except directories)."""
        return [e for e in self.entries if e.kind is not EntryKind.DIRECTORY]


def _classify_symlink(path: Path, root: Path) -> tuple[EntryKind, int | None]:
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return EntryKind.SYMLINK_BROKEN, None
    if not target.is_relative_to(root):
        return EntryKind.SYMLINK_ESCAPE, None
    if target.is_file():
        return EntryKind.FILE, target.stat().st_size
    if target.is_dir():
        return EntryKind.DIRECTORY, None
    return EntryKind.SPECIAL, None


def scan_assets(root: Path, *, recursive: bool = False, label: str = "assets") -> AssetInventory:
    """List *root* (optionally recursively) without following symlinked directories."""
    try:
        root_real = root.resolve(strict=True)
    except FileNotFoundError:
        raise InputError(f"{label} directory not found: {root}") from None
    except OSError as exc:
        raise InputError(f"cannot access {label} directory {root}: {exc.strerror or exc}") from None
    if not root_real.is_dir():
        raise InputError(f"{label} path is not a directory: {root}")

    entries: list[AssetEntry] = []
    ignored = 0
    skipped = 0
    seen = 0
    stack: list[tuple[Path, str, int]] = [(root_real, "", 0)]
    while stack:
        directory, prefix, depth = stack.pop()
        try:
            iterator = os.scandir(directory)
        except PermissionError:
            raise InputError(
                f"permission denied listing {label} directory: {directory.name}"
            ) from None
        except OSError as exc:
            raise InputError(f"cannot list {label} directory: {exc.strerror or exc}") from None
        with iterator:
            for item in iterator:
                seen += 1
                if seen > MAX_ENTRIES:
                    raise InputError(f"{label} directory has more than {MAX_ENTRIES} entries")
                name = item.name
                relpath = prefix + name
                if name.startswith(".") or name.casefold() in IGNORED_NAMES:
                    ignored += 1
                    continue
                path = Path(item.path)
                size: int | None = None
                if item.is_symlink():
                    kind, size = _classify_symlink(path, root_real)
                elif item.is_dir(follow_symlinks=False):
                    kind = EntryKind.DIRECTORY
                    if recursive and depth < MAX_DEPTH:
                        stack.append((path, relpath + "/", depth + 1))
                    else:
                        skipped += 1
                elif item.is_file(follow_symlinks=False):
                    kind = EntryKind.FILE
                    size = item.stat(follow_symlinks=False).st_size
                else:
                    kind = EntryKind.SPECIAL
                entries.append(AssetEntry(name, relpath, path, kind, size))
    entries.sort(key=lambda e: e.relpath)
    return AssetInventory(tuple(entries), ignored, skipped)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def check_assets(
    ctx: LintContext, rows: list[RowView], inventory: AssetInventory
) -> list[tuple[RowView, AssetEntry]]:
    """Match CSV filenames to inventory entries. Returns exact regular-file matches."""
    by_name: dict[str, list[AssetEntry]] = defaultdict(list)
    by_nfc: dict[str, list[AssetEntry]] = defaultdict(list)
    by_fold: dict[str, list[AssetEntry]] = defaultdict(list)
    for entry in inventory.entries:
        by_name[entry.name].append(entry)
        by_nfc[_nfc(entry.name)].append(entry)
        by_fold[_nfc(entry.name).casefold()].append(entry)

    files = inventory.files
    if not files:
        ctx.emit(
            "ASSET-DIR-EMPTY",
            "The asset directory contains no candidate files"
            + (
                f" ({inventory.ignored} hidden/system files ignored)." if inventory.ignored else "."
            ),
            suggestion="Point --assets at the folder that holds the media files.",
        )

    collisions: dict[tuple[str, str], list[AssetEntry]] = defaultdict(list)
    for entry in files:
        parent = entry.relpath[: -len(entry.name)]
        collisions[(parent, _nfc(entry.name).casefold())].append(entry)
    for group in collisions.values():
        if len(group) > 1:
            names = ", ".join(f'"{e.relpath}"' for e in group)
            ctx.emit(
                "ASSET-CASE-COLLISION",
                f"Files differ only by case: {names}.",
                filename=group[0].relpath,
                suggestion="Rename so names stay unique on case-insensitive file systems.",
            )

    referenced: set[str] = set()
    matched: list[tuple[RowView, AssetEntry]] = []
    for row in rows:
        name = row.filename
        if not row.aligned or not name or not name.strip() or path_problem(name):
            continue
        loc: dict[str, Any] = {
            "line": row.line,
            "row": row.row,
            "column": "Filename",
            "filename": name,
        }
        hits = by_name.get(name)
        if hits:
            entry = hits[0]
            if len(hits) > 1:
                ctx.emit(
                    "ASSET-AMBIGUOUS",
                    f'"{excerpt(name, 50)}" exists in several folders: '
                    + ", ".join(e.relpath for e in hits)
                    + f"; using {entry.relpath}.",
                    **loc,
                    suggestion="Keep one copy per file name in the batch folder.",
                )
            referenced.update(e.relpath for e in hits)
            _check_entry(ctx, entry, loc, matched, row)
            continue
        nfc_hits = by_nfc.get(_nfc(name))
        fold_hits = by_fold.get(_nfc(name).casefold())
        trimmed_hits = by_name.get(name.strip()) if name != name.strip() else None
        if nfc_hits:
            referenced.update(e.relpath for e in nfc_hits)
            ctx.emit(
                "ASSET-UNICODE-MISMATCH",
                f'"{excerpt(name, 50)}" matches "{nfc_hits[0].relpath}" only after Unicode '
                "normalization (NFC/NFD).",
                **loc,
                suggestion="Rename the file or edit the cell so both use the same (NFC) spelling.",
            )
        elif fold_hits:
            referenced.update(e.relpath for e in fold_hits)
            ctx.emit(
                "ASSET-CASE-MISMATCH",
                f'No file named "{excerpt(name, 50)}"; "{fold_hits[0].relpath}" differs only by '
                "letter case.",
                **loc,
                suggestion=f'Use the exact name "{fold_hits[0].name}" in the CSV or rename the file.',
            )
        elif trimmed_hits:
            referenced.update(e.relpath for e in trimmed_hits)
            ctx.emit(
                "ASSET-MISSING",
                f'No file named "{excerpt(name, 50)}"; a file matches after removing surrounding '
                "whitespace.",
                **loc,
                suggestion="Remove the whitespace from the Filename cell.",
            )
        else:
            close = difflib.get_close_matches(name, [e.name for e in files], n=1, cutoff=0.75)
            hint = f' Closest file: "{close[0]}".' if close else ""
            ctx.emit(
                "ASSET-MISSING",
                f'No file named "{excerpt(name, 50)}" in the asset directory.{hint}',
                **loc,
                suggestion="Check the spelling and extension, or add the file.",
            )

    for entry in files:
        if entry.relpath not in referenced and entry.kind is EntryKind.FILE:
            ctx.emit(
                "ASSET-ORPHAN",
                f'"{entry.relpath}" has no row in the CSV.',
                filename=entry.relpath,
                suggestion="Add a CSV row for it or move it out of the batch folder.",
            )
    return matched


def _check_entry(
    ctx: LintContext,
    entry: AssetEntry,
    loc: dict[str, Any],
    matched: list[tuple[RowView, AssetEntry]],
    row: RowView,
) -> None:
    if entry.kind is EntryKind.SYMLINK_ESCAPE:
        ctx.emit(
            "ASSET-SYMLINK-ESCAPE",
            f'"{entry.relpath}" is a symbolic link that resolves outside the asset directory; '
            "it was not followed.",
            **loc,
            suggestion="Copy the real file into the batch folder.",
        )
    elif entry.kind is EntryKind.SYMLINK_BROKEN:
        ctx.emit(
            "ASSET-SYMLINK-BROKEN",
            f'"{entry.relpath}" is a broken symbolic link.',
            **loc,
            suggestion="Replace the link with the real file.",
        )
    elif entry.kind is not EntryKind.FILE:
        ctx.emit(
            "ASSET-NOT-REGULAR-FILE",
            f'"{entry.relpath}" is a {entry.kind.value}, not a file.',
            **loc,
            suggestion="Use a regular media file.",
        )
    elif entry.size == 0:
        ctx.emit(
            "ASSET-EMPTY-FILE",
            f'"{entry.relpath}" is empty (0 bytes).',
            **loc,
            suggestion="Re-export the media file.",
        )
    else:
        matched.append((row, entry))


def check_releases(ctx: LintContext, rows: list[RowView], inventory: AssetInventory) -> None:
    available = {e.name for e in inventory.entries if e.kind is EntryKind.FILE}
    for row in rows:
        if not row.aligned or not row.releases:
            continue
        for name in (part.strip() for part in row.releases.split(",")):
            if not name:
                continue
            candidates = [name] + [name + ext for ext in RELEASE_EXTENSIONS]
            if path_problem(name):
                detail = "is not a bare file name, so it was not looked up"
            elif not any(c in available for c in candidates):
                tried = name if PurePath(name).suffix else f"{name}, {name}.jpg, {name}.jpeg"
                detail = f"was not found in the releases directory (tried {tried})"
            else:
                continue
            ctx.emit(
                "ASSET-RELEASE-MISSING",
                f'Release "{excerpt(name, 40)}" {detail}.',
                line=row.line,
                row=row.row,
                column="Releases",
                filename=row.filename or None,
                suggestion="Check the release name or add the release JPEG locally.",
            )
