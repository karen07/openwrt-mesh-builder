#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from .process import die, need, run_captured
    from .default import PACKAGE_REPO_INDEX_FILES
except ImportError:
    from process import die, need, run_captured
    from default import PACKAGE_REPO_INDEX_FILES


@dataclass(frozen=True)
class ApkMeta:
    name: str
    version: str
    arch: str


def remove_package_indexes(package_dir: Path) -> None:
    for name in PACKAGE_REPO_INDEX_FILES:
        path = package_dir / name
        if path.exists():
            path.unlink()


def _capture_apk(args: list[str]):
    need("apk")
    return run_captured(["apk", *args])


def read_apk_metadata(path: Path) -> ApkMeta:
    """Read APK package metadata through apk-tools.

    apk-tools 3.x owns APK v3/ADB parsing.  This wrapper intentionally avoids a
    project-local binary APK parser.  It supports common apk-tools output forms
    and fails fast if the installed apk does not expose package metadata for a
    local .apk file.
    """
    if not path.is_file():
        die(f"missing apk package: {path}")

    # `apk info` and `apk query` are database/repository oriented and fail on
    # non-Alpine hosts without an APK database.  For a local APK v3 file, use
    # `apk adbdump`, which dumps the package ADB metadata directly.
    candidates = [
        ["adbdump", str(path)],
        ["manifest", str(path)],
    ]
    errors: list[str] = []
    for args in candidates:
        result = _capture_apk(args)
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            errors.append(f"apk {' '.join(args)}: {err or f'exit {result.returncode}'}")
            continue
        meta = parse_apk_metadata_text(result.stdout)
        if meta is not None:
            return meta
        errors.append(f"apk {' '.join(args)}: metadata fields not found")

    detail = "; ".join(errors)
    suffix = f": {detail}" if detail else ""
    die(f"failed to read APK metadata for {path} with apk-tools" + suffix)


def _clean_apk_value(value: str) -> str:
    value = value.strip().rstrip(",;")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def parse_apk_metadata_text(text: str) -> ApkMeta | None:
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # .PKGINFO style: pkgname = foo, arch = x, pkgver = 1.0-r0
        if " = " in line:
            key, value = line.split(" = ", 1)
            fields[key.strip().lower()] = _clean_apk_value(value)
            continue
        # ADB/object-ish text output: name: foo / version: 1.0 / arch: x
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = _clean_apk_value(value)
            continue
    name = fields.get("pkgname") or fields.get("name")
    version = fields.get("pkgver") or fields.get("version")
    arch = fields.get("arch")
    if name and version and arch:
        return ApkMeta(name=name, version=version, arch=arch)

    # Last-resort support for outputs that print the package identity in one line.
    m = re.search(
        r"(?m)^([A-Za-z0-9_.+:-]+)-([0-9][A-Za-z0-9_.:+~\-]*)"
        r"\s+arch[:=]\s*([A-Za-z0-9_.-]+)$",
        text,
    )
    if m:
        return ApkMeta(name=m.group(1), version=m.group(2), arch=m.group(3))
    return None


def apk_canonical_name(path: Path, expected_arch: str) -> str:
    meta = read_apk_metadata(path)
    if meta.arch not in {expected_arch, "noarch"}:
        die(f"{path}: bad APK arch: expected {expected_arch}, got {meta.arch}")
    return f"{meta.name}-{meta.version}.apk"
