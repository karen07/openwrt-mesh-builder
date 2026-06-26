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
    from .secrets import decrypt_text as decrypt_owmb_text
except ImportError:
    import importlib.util

    from default import FILE_MODE_MASK
    from process import die

    _secrets_path = Path(__file__).with_name("secrets.py")
    _secrets_spec = importlib.util.spec_from_file_location(
        "owmb_local_secrets", _secrets_path
    )
    if _secrets_spec is None or _secrets_spec.loader is None:
        raise ImportError(f"cannot load {_secrets_path}")
    _secrets_module = importlib.util.module_from_spec(_secrets_spec)
    _secrets_spec.loader.exec_module(_secrets_module)
    decrypt_owmb_text = _secrets_module.decrypt_text


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
    # OWMB encryption uses a fresh random nonce for every encrypted marker.
    # A regenerated file can therefore be byte-different while decrypting to
    # exactly the same plaintext. Keep the existing file only when the old file
    # is already in the encrypted on-disk form. If the old file is plaintext or
    # uses OWMB_PLAIN_* markers and the new file uses OWMB_ENC_* markers, write
    # the new text so generation also performs one-pass migration.
    if not has_encrypted_owmb_marker(old_text):
        return False
    if has_plain_owmb_marker(old_text):
        return False
    if not has_encrypted_owmb_marker(new_text):
        return False
    if has_plain_owmb_marker(new_text):
        return False
    return True


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old_text = path.read_text(encoding="utf-8")
        if old_text == text:
            return
        if has_any_owmb_marker(old_text) or has_any_owmb_marker(text):
            old_plain = decrypt_owmb_text(old_text, where=str(path))
            new_plain = decrypt_owmb_text(text, where=str(path))
            if old_plain == new_plain and encrypted_owmb_state_is_current(
                old_text, text
            ):
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
