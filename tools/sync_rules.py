#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re
import shutil
import tempfile
from pathlib import Path

try:
    from .process import die
    from .common import RouterDef
    from .file_ops import copy_file_if_changed, remove_path
    from .default import (
        FILE_MODE_MASK,
        FIREWALL_MARKER,
        SYNC_COPY_DIRS,
        SYNC_COPY_FILES,
        SYNC_MERGE_FILES,
    )
except ImportError:
    from process import die
    from common import RouterDef
    from file_ops import copy_file_if_changed, remove_path  # type: ignore
    from default import (
        FILE_MODE_MASK,
        FIREWALL_MARKER,
        SYNC_COPY_DIRS,
        SYNC_COPY_FILES,
        SYNC_MERGE_FILES,
    )

MARKER_RE = re.compile(rf"^{re.escape(FIREWALL_MARKER)}\s*$")


def router_relpath(router: RouterDef, rel: str | Path) -> Path:
    return router.path / rel


def find_marker_index(lines: list[str], path: Path) -> int:
    for i, line in enumerate(lines):
        if MARKER_RE.match(line.rstrip("\n")):
            return i
    die(f"marker not found in {path}")


def write_text_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == text:
        return

    print(f"Updating {path}")
    old_mode = path.stat().st_mode if path.exists() else None

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)

    if old_mode is not None:
        tmp_path.chmod(old_mode & FILE_MODE_MASK)

    tmp_path.replace(path)


def copy_tree_initial(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    if not src.exists() or not src.is_dir():
        die(f"source directory does not exist: {src}")

    print(f"Creating {dst} from {src}")
    shutil.copytree(src, dst, copy_function=shutil.copy2)


def ensure_router_from_example(source_dir: Path, target: RouterDef) -> None:
    copy_tree_initial(source_dir, target.path)


def merge_after_mark(dst: Path, src: Path) -> None:
    if not src.exists():
        die(f"merge source does not exist: {src}")
    if not dst.exists():
        copy_file_if_changed(src, dst)
        return

    dst_lines = dst.read_text(encoding="utf-8").splitlines(keepends=True)
    src_lines = src.read_text(encoding="utf-8").splitlines(keepends=True)

    dst_marker = find_marker_index(dst_lines, dst)
    src_marker = find_marker_index(src_lines, src)

    write_text_if_changed(
        dst, "".join(dst_lines[: dst_marker + 1] + src_lines[src_marker + 1 :])
    )


def copy_dir(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        die(f"source directory does not exist: {src}")

    dst.mkdir(parents=True, exist_ok=True)

    expected: set[Path] = set()
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        out = dst / rel
        expected.add(rel)

        if item.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            copy_file_if_changed(item, out)

    for item in sorted(dst.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = item.relative_to(dst)
        if rel not in expected:
            remove_path(item)


def copy_file(src: Path, dst: Path) -> None:
    copy_file_if_changed(src, dst)


def sync_router(source_dir: Path, target: RouterDef) -> None:
    for rel in SYNC_COPY_DIRS:
        copy_dir(src=source_dir / rel, dst=router_relpath(target, rel))

    for rel in SYNC_COPY_FILES:
        copy_file(src=source_dir / rel, dst=router_relpath(target, rel))

    for rel in SYNC_MERGE_FILES:
        merge_after_mark(dst=router_relpath(target, rel), src=source_dir / rel)
