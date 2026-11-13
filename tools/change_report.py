#!/usr/bin/env python3
"""Report net file changes across a clean-and-regenerate operation."""

import hashlib
import os
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

_CHANGE_LOGS_MUTED: ContextVar[bool] = ContextVar(
    "owmb_change_logs_muted", default=False
)


def log_change(message: str) -> None:
    if not _CHANGE_LOGS_MUTED.get():
        print(message)


@contextmanager
def mute_intermediate_changes() -> Iterator[None]:
    token = _CHANGE_LOGS_MUTED.set(True)
    try:
        yield
    finally:
        _CHANGE_LOGS_MUTED.reset(token)


def file_fingerprint(path: Path) -> tuple[str, int, str]:
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if path.is_symlink():
        return ("symlink", mode, os.readlink(path))
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return ("file", mode, digest.hexdigest())
    return ("other", mode, "")


def snapshot_files(roots: list[Path]) -> dict[Path, tuple[str, int, str]]:
    snapshot = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() or path.is_symlink():
                snapshot[path] = file_fingerprint(path)
    return snapshot


def report_file_changes(
    before: dict[Path, tuple[str, int, str]],
    after: dict[Path, tuple[str, int, str]],
) -> None:
    updated = sorted(path for path in after if before.get(path) != after[path])
    removed = sorted(path for path in before if path not in after)
    for path in updated:
        print(f"Updating {path}")
    for path in removed:
        print(f"Removing {path}")
    if not updated and not removed:
        print("No generated file changes.")
