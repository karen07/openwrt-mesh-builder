#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import filecmp
import shutil
import tempfile
from pathlib import Path

try:
    from .default import FILE_MODE_MASK
    from .process import die
except ImportError:
    from default import FILE_MODE_MASK
    from process import die


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_output(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == text:
        return

    old_mode = path.stat().st_mode if path.exists() else None

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)

    if old_mode is not None:
        tmp_path.chmod(old_mode & FILE_MODE_MASK)

    tmp_path.replace(path)


OWMB_ENC_MARKERS = ("OWMB_ENC_SECRET_V1", "OWMB_ENC_MATERIAL_V1")
OWMB_PLAIN_MARKERS = ("OWMB_PLAIN_SECRET_V1", "OWMB_PLAIN_MATERIAL_V1")


def has_any_owmb_marker(text: str) -> bool:
    return "OWMB_" in text


def has_encrypted_owmb_marker(text: str) -> bool:
    return any(marker in text for marker in OWMB_ENC_MARKERS)


def has_plain_owmb_marker(text: str) -> bool:
    return any(marker in text for marker in OWMB_PLAIN_MARKERS)


def encrypted_owmb_state_is_current(old_text: str, new_text: str) -> bool:
    # Deprecated compatibility helper kept for imports from tools.common.
    # Generated files must follow the exact target text produced from config.json
    # and preserved key-material state. The generic file writer therefore no
    # longer treats "decrypts to the same plaintext" as "no change".
    return old_text == new_text


def write(path: Path, text: str) -> None:
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
        tmp_path.chmod(old_mode)

    tmp_path.replace(path)


def rm(path: Path) -> None:
    if not path.exists():
        return
    print(f"Removing {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def remove_path(path: Path) -> None:
    rm(path)


def copy_file_if_changed(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        die(f"source file does not exist: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() and dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        return

    print(f"Updating {dst}")
    shutil.copy2(src, dst)


def cp_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if not src.is_dir():
        die(f"template path is not a directory: {src}")

    for item in src.rglob("*"):
        out = dst / item.relative_to(src)
        if item.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if item.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() and item.read_bytes() == out.read_bytes():
                continue
            print(f"Updating {out}")
            shutil.copy2(item, out)
