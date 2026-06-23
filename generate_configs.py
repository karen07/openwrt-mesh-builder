#!/usr/bin/env python3
import struct
import sys
import zlib

sys.dont_write_bytecode = True
import argparse
import filecmp
import importlib
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from tools.cli_common import (
    clear_screen,
    die,
    load_json_config,
    urlopen_insecure,
)
from tools.common import ConfigData, DeviceProfile, RouterDef, build_config_data
from tools.default import (
    CONFIG_PATH,
    AWG_PACKAGE_NAMES,
    AWG_RELEASE_BASE_URL,
    MIN_OPENWRT_VERSION_TEXT,
    PACKAGE_EXTENSION,
    PACKAGE_REPO_INDEX_FILES,
    PACKAGE_SOURCE_ROOT,
    ROUTER_EXAMPLE_DIR as EXAMPLE_ROUTER_DIR,
    ROUTER_PACKAGES_DIRNAME,
)
from tools.sync_rules import ensure_router_from_example, sync_router


@dataclass(frozen=True)
class ApkMeta:
    name: str
    version: str
    arch: str


ADB_FORMAT_MAGIC = b"ADB."
ADB_COMPRESSED_DEFLATE_MAGIC = b"ADBd"
ADB_COMPRESSED_CUSTOM_MAGIC = b"ADBc"
ADB_SCHEMA_PACKAGE = 0x676B6370
ADB_BLOCK_ALIGNMENT = 8
ADB_BLOCK_ADB = 0
ADB_BLOCK_EXT = 3
ADB_COMP_NONE = 0
ADB_COMP_DEFLATE = 1
ADB_TYPE_BLOB_8 = 0x80000000
ADB_TYPE_BLOB_16 = 0x90000000
ADB_TYPE_BLOB_32 = 0xA0000000
ADB_TYPE_OBJECT = 0xE0000000
ADB_TYPE_MASK = 0xF0000000
ADB_VALUE_MASK = 0x0FFFFFFF
ADBI_PKG_PKGINFO = 0x01
ADBI_PI_NAME = 0x01
ADBI_PI_VERSION = 0x02
ADBI_PI_ARCH = 0x05
def run(
    args: list[str],
    cwd: Path | None = None,
    quiet: bool = False,
) -> None:
    if quiet:
        run_checked(args, cwd=cwd, quiet=True)
    else:
        run_no_capture(args, cwd=cwd)


def ensure_example_router_dir() -> None:
    if not EXAMPLE_ROUTER_DIR.is_dir():
        die(f"missing example router directory: {EXAMPLE_ROUTER_DIR}")


def run_python_main(module_name: str, args: list[str]) -> None:
    module = importlib.import_module(module_name)
    old_argv = sys.argv
    sys.argv = [module_name.rsplit(".", 1)[-1] + ".py", *args]
    try:
        module.main()
    finally:
        sys.argv = old_argv


def router_device_profile(cfg: ConfigData, router: RouterDef) -> DeviceProfile:
    return cfg.device_profiles[router.device_profile]


def profile_arch(profile: DeviceProfile) -> str:
    return profile.arch


def profile_board_arch(profile: DeviceProfile) -> tuple[str, str, str, str]:
    return profile.board, profile.arch, profile.target, profile.subtarget


def package_source_dir_from_profile(version: str, profile: DeviceProfile) -> Path:
    return PACKAGE_SOURCE_ROOT / version / profile.board / profile.arch


def remove_package_indexes(package_dir: Path) -> None:
    for name in PACKAGE_REPO_INDEX_FILES:
        path = package_dir / name
        if path.exists():
            path.unlink()


def download_binary(url: str, dst: Path) -> bool:
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.unlink(missing_ok=True)

    try:
        with urlopen_insecure(url, timeout=60) as response:
            data = response.read()
    except Exception:
        tmp.unlink(missing_ok=True)
        return False

    if not data:
        tmp.unlink(missing_ok=True)
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    tmp.replace(dst)
    return True


def ensure_named_awg_packages_for_profile(
    version: str,
    profile: DeviceProfile,
) -> None:
    board, arch, target, subtarget = profile_board_arch(profile)

    dst_dir = package_source_dir_from_profile(version, profile)
    dst_dir.mkdir(parents=True, exist_ok=True)
    remove_package_indexes(dst_dir)

    postfix = f"_v{version}_{arch}_{target}_{subtarget}"
    base_url = f"{AWG_RELEASE_BASE_URL}/v{version}"

    for package_name in AWG_PACKAGE_NAMES:
        simple_dst = dst_dir / f"{package_name}.{PACKAGE_EXTENSION}"

        if simple_dst.is_file() and simple_dst.stat().st_size > 0:
            continue

        release_file_name = f"{package_name}{postfix}.{PACKAGE_EXTENSION}"
        url = f"{base_url}/{release_file_name}"
        tmp_dst = dst_dir / release_file_name

        if not download_binary(url, tmp_dst):
            die(
                "failed to download AWG2 apk package "
                f"{package_name} for {version} {board} {arch}. Tried: {url}"
            )

        tmp_dst.replace(simple_dst)
        print(f"Downloaded: {simple_dst}")


def ensure_awg_packages(
    cfg: ConfigData,
    routers: list[RouterDef],
    version: str,
) -> None:
    seen: set[tuple[str, str]] = set()

    for router in routers:
        profile = router_device_profile(cfg, router)

        board, arch, _target, _subtarget = profile_board_arch(profile)
        key = (board, arch)
        if key in seen:
            continue

        seen.add(key)
        ensure_named_awg_packages_for_profile(version, profile)


def adb_decompress(data: bytes, apk_file: Path) -> bytes:
    if data.startswith(ADB_FORMAT_MAGIC):
        return data

    if data.startswith(ADB_COMPRESSED_DEFLATE_MAGIC):
        try:
            return zlib.decompress(data[4:], -zlib.MAX_WBITS)
        except zlib.error as e:
            die(f"failed to decompress apk metadata from {apk_file}: {e}")

    if data.startswith(ADB_COMPRESSED_CUSTOM_MAGIC):
        if len(data) < 6:
            die(f"truncated apk compression header: {apk_file}")

        alg = data[4]
        payload = data[6:]

        if alg == ADB_COMP_NONE:
            return payload

        if alg == ADB_COMP_DEFLATE:
            try:
                return zlib.decompress(payload, -zlib.MAX_WBITS)
            except zlib.error as e:
                die(f"failed to decompress apk metadata from {apk_file}: {e}")

        die(
            f"unsupported apk metadata compression in {apk_file}: "
            "only none and deflate are supported without external dependencies"
        )

    die(f"unsupported apk metadata format: {apk_file}")


def read_u32(data: bytes, offset: int, apk_file: Path) -> int:
    if offset < 0 or offset + 4 > len(data):
        die(f"truncated apk metadata in {apk_file}")
    return struct.unpack_from("<I", data, offset)[0]

def parse_pkginfo(text: str, apk_file: Path) -> ApkMeta:
    fields: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")

        if key and key not in fields:
            fields[key] = value

    name = fields.get("pkgname")
    version = fields.get("pkgver")
    arch = fields.get("arch")

    if not name or not version or not arch:
        die(
            f"incomplete apk metadata in {apk_file}: "
            f"pkgname={name!r}, pkgver={version!r}, arch={arch!r}"
        )

    return ApkMeta(name=name, version=version, arch=arch)


ADB_SCHEMA_PACKAGE = 0x676B6370
ADB_COMPRESSION_NONE = 0x2E
ADB_COMPRESSION_DEFLATE = 0x64
ADB_COMPRESSION_CUSTOM = 0x63
ADB_CUSTOM_COMPRESSION_NONE = 0
ADB_CUSTOM_COMPRESSION_DEFLATE = 1
ADB_CUSTOM_COMPRESSION_ZSTD = 2
ADB_BLOCK_ADB = 0
ADB_VALUE_INT = 0x10000000
ADB_VALUE_INT32 = 0x20000000
ADB_VALUE_INT64 = 0x30000000
ADB_VALUE_BLOB8 = 0x80000000
ADB_VALUE_BLOB16 = 0x90000000
ADB_VALUE_BLOB32 = 0xA0000000
ADB_VALUE_ARRAY = 0xD0000000
ADB_VALUE_OBJECT = 0xE0000000
ADB_VALUE_TYPE_MASK = 0xF0000000
ADB_VALUE_PAYLOAD_MASK = 0x0FFFFFFF


@dataclass(frozen=True)
class AdbValue:
    value_type: int
    value: int


def uint_from(data: bytes | bytearray) -> int:
    return int.from_bytes(data, "little", signed=False)

def adb_value_type(value: int) -> int:
    return value & ADB_TYPE_MASK


def adb_value_offset(value: int) -> int:
    return value & ADB_VALUE_MASK


def adb_read_object(data: bytes, value: int, apk_file: Path) -> list[int]:
    if adb_value_type(value) != ADB_TYPE_OBJECT:
        die(f"bad apk metadata object in {apk_file}")

    offset = adb_value_offset(value)
    count = read_u32(data, offset, apk_file)
    if count == 0:
        die(f"empty apk metadata object in {apk_file}")

    end = offset + count * 4
    if end > len(data):
        die(f"truncated apk metadata object in {apk_file}")

    return list(struct.unpack_from(f"<{count}I", data, offset))


def adb_object_field(values: list[int], index: int) -> int:
    if index >= len(values):
        return 0
    return values[index]


def adb_read_blob(data: bytes, value: int, apk_file: Path) -> str:
    value_type = adb_value_type(value)
    offset = adb_value_offset(value)

    if value_type == ADB_TYPE_BLOB_8:
        if offset + 1 > len(data):
            die(f"truncated apk metadata blob in {apk_file}")
        size = data[offset]
        start = offset + 1
    elif value_type == ADB_TYPE_BLOB_16:
        if offset + 2 > len(data):
            die(f"truncated apk metadata blob in {apk_file}")
        size = struct.unpack_from("<H", data, offset)[0]
        start = offset + 2
    elif value_type == ADB_TYPE_BLOB_32:
        size = read_u32(data, offset, apk_file)
        start = offset + 4
    else:
        die(f"bad apk metadata blob in {apk_file}")

    end = start + size
    if end > len(data):
        die(f"truncated apk metadata blob in {apk_file}")

    try:
        return data[start:end].decode("utf-8")
    except UnicodeDecodeError as e:
        die(f"bad apk metadata text in {apk_file}: {e}")


def adb_first_block_payload(data: bytes, apk_file: Path) -> bytes:
    if len(data) < 8 or data[:4] != ADB_FORMAT_MAGIC:
        die(f"bad apk metadata header: {apk_file}")

    schema = read_u32(data, 4, apk_file)
    if schema != ADB_SCHEMA_PACKAGE:
        die(f"unsupported apk metadata schema in {apk_file}: 0x{schema:08x}")

    offset = 8
    if offset + 4 > len(data):
        die(f"missing apk metadata block: {apk_file}")

    type_size = read_u32(data, offset, apk_file)
    block_type = type_size >> 30
    raw_size = type_size & 0x3FFFFFFF
    header_size = 4

    if block_type == ADB_BLOCK_EXT:
        if offset + 16 > len(data):
            die(f"truncated apk metadata extended block: {apk_file}")
        block_type = raw_size
        raw_size = struct.unpack_from("<Q", data, offset + 8)[0]
        header_size = 16

    if block_type != ADB_BLOCK_ADB:
        die(f"missing apk metadata ADB block: {apk_file}")

    if raw_size < header_size:
        die(f"bad apk metadata block size: {apk_file}")

    end = offset + raw_size
    padded_end = offset + ((raw_size + ADB_BLOCK_ALIGNMENT - 1) // ADB_BLOCK_ALIGNMENT) * ADB_BLOCK_ALIGNMENT
    if end > len(data) or padded_end > len(data):
        die(f"truncated apk metadata block: {apk_file}")

    return data[offset + header_size : end]
def adb_value_from_u32(value: int) -> AdbValue | None:
    if value == 0:
        return None
    return AdbValue(value & ADB_VALUE_TYPE_MASK, value & ADB_VALUE_PAYLOAD_MASK)


def adb_payload_bounds(
    data: bytes | bytearray, offset: int, size: int, what: str
) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(
            f"invalid APK v3 ADB {what} bounds: "
            f"offset={offset}, size={size}, adb_size={len(data)}"
        )


def adb_read_u32(data: bytes | bytearray, offset: int, what: str) -> int:
    adb_payload_bounds(data, offset, 4, what)
    return uint_from(data[offset : offset + 4])


def adb_read_values(data: bytes | bytearray, header: AdbValue) -> list[AdbValue | None]:
    if header.value_type not in {ADB_VALUE_ARRAY, ADB_VALUE_OBJECT}:
        raise ValueError(
            f"expected APK v3 ADB array/object, got {header.value_type:#x}"
        )

    count = adb_read_u32(data, header.value, "array/object slot count")
    if count < 1:
        raise ValueError(f"invalid APK v3 ADB array/object slot count: {count}")

    values: list[AdbValue | None] = []
    for index in range(1, count):
        raw = adb_read_u32(data, header.value + index * 4, "array/object slot")
        values.append(adb_value_from_u32(raw))
    return values


def adb_value_at(values: list[AdbValue | None], field_index: int) -> AdbValue | None:
    if field_index <= 0 or field_index > len(values):
        return None
    return values[field_index - 1]


def adb_read_uint(data: bytes | bytearray, header: AdbValue) -> int:
    if header.value_type == ADB_VALUE_INT:
        return header.value
    if header.value_type == ADB_VALUE_INT32:
        return adb_read_u32(data, header.value, "int32")
    if header.value_type == ADB_VALUE_INT64:
        adb_payload_bounds(data, header.value, 8, "int64")
        return uint_from(data[header.value : header.value + 8])
    raise ValueError(f"expected APK v3 ADB integer, got {header.value_type:#x}")


def adb_read_blob(data: bytes | bytearray, header: AdbValue) -> bytes:
    if header.value_type == ADB_VALUE_BLOB8:
        size_len = 1
    elif header.value_type == ADB_VALUE_BLOB16:
        size_len = 2
    elif header.value_type == ADB_VALUE_BLOB32:
        size_len = 4
    else:
        raise ValueError(f"expected APK v3 ADB blob, got {header.value_type:#x}")

    adb_payload_bounds(data, header.value, size_len, "blob size")
    size = uint_from(data[header.value : header.value + size_len])
    offset = header.value + size_len
    adb_payload_bounds(data, offset, size, "blob data")
    return bytes(data[offset : offset + size])


def adb_read_text(data: bytes | bytearray, header: AdbValue) -> str:
    return adb_read_blob(data, header).decode("utf-8")


def parse_apk_v3_pkginfo_adb(data: bytes | bytearray, apk_file: Path) -> ApkMeta:
    if len(data) < 8:
        raise ValueError("APK v3 ADB block is too small")

    root_raw = adb_read_u32(data, 4, "root object")
    root = adb_value_from_u32(root_raw)
    if root is None or root.value_type != ADB_VALUE_OBJECT:
        raise ValueError("APK v3 ADB root is not an object")

    root_values = adb_read_values(data, root)
    pkginfo = adb_value_at(root_values, 1)
    if pkginfo is None or pkginfo.value_type != ADB_VALUE_OBJECT:
        raise ValueError("APK v3 ADB pkginfo field is missing or not an object")

    info_values = adb_read_values(data, pkginfo)

    name_value = adb_value_at(info_values, 1)
    version_value = adb_value_at(info_values, 2)
    arch_value = adb_value_at(info_values, 5)

    if name_value is None or version_value is None or arch_value is None:
        raise ValueError("APK v3 ADB pkginfo has no name/version/arch fields")

    meta = ApkMeta(
        name=adb_read_text(data, name_value),
        version=adb_read_text(data, version_value),
        arch=adb_read_text(data, arch_value),
    )

    if not meta.name or not meta.version or not meta.arch:
        raise ValueError(
            f"incomplete APK v3 metadata in {apk_file}: "
            f"name={meta.name!r}, version={meta.version!r}, arch={meta.arch!r}"
        )

    return meta


def deflate_raw(data: bytes) -> bytes:
    import zlib

    return zlib.decompress(data, wbits=-zlib.MAX_WBITS)


def apk_v3_payload(data: bytes) -> bytes:
    if len(data) < 4:
        raise ValueError("file is too small for APK v3 header")
    if data[:3] != b"ADB":
        raise ValueError("file does not start with APK v3 ADB header")

    compression = data[3]
    payload = data[4:]

    if compression == ADB_COMPRESSION_NONE:
        return payload

    if compression == ADB_COMPRESSION_DEFLATE:
        decompressed = deflate_raw(payload)
        if not decompressed.startswith(b"ADB."):
            raise ValueError(
                "deflated APK v3 stream does not start with inner ADB. header"
            )
        return decompressed[4:]

    if compression == ADB_COMPRESSION_CUSTOM:
        if len(payload) < 2:
            raise ValueError("truncated APK v3 custom compression header")
        alg = payload[0]
        compressed_payload = payload[2:]

        if alg == ADB_CUSTOM_COMPRESSION_NONE:
            return compressed_payload
        if alg == ADB_CUSTOM_COMPRESSION_DEFLATE:
            decompressed = deflate_raw(compressed_payload)
            if not decompressed.startswith(b"ADB."):
                raise ValueError(
                    "custom-deflated APK v3 stream does not start with inner ADB. header"
                )
            return decompressed[4:]
        if alg == ADB_CUSTOM_COMPRESSION_ZSTD:
            raise ValueError(
                "APK v3 zstd compression is not supported by this pure-Python parser"
            )

        raise ValueError(f"unknown APK v3 custom compression algorithm: {alg}")

    raise ValueError(f"unknown APK v3 compression marker: 0x{compression:02x}")

def apk_metadata(apk_file: Path) -> ApkMeta:
    adb_data = adb_decompress(apk_file.read_bytes(), apk_file)
    block = adb_first_block_payload(adb_data, apk_file)

    if len(block) < 8:
        die(f"truncated apk package metadata: {apk_file}")
    if block[0] != 0:
        die(f"incompatible apk package metadata version: {apk_file}")

    root_value = read_u32(block, 4, apk_file)
    package = adb_read_object(block, root_value, apk_file)
    pkginfo_value = adb_object_field(package, ADBI_PKG_PKGINFO)
    pkginfo = adb_read_object(block, pkginfo_value, apk_file)

    name = adb_read_blob(block, adb_object_field(pkginfo, ADBI_PI_NAME), apk_file)
    version = adb_read_blob(block, adb_object_field(pkginfo, ADBI_PI_VERSION), apk_file)
    arch = adb_read_blob(block, adb_object_field(pkginfo, ADBI_PI_ARCH), apk_file)

    if not name or not version or not arch:
        die(f"incomplete apk metadata in: {apk_file}")

    return ApkMeta(name=name, version=version, arch=arch)

def parse_apk_v3_metadata(apk_file: Path) -> ApkMeta:
    payload = apk_v3_payload(apk_file.read_bytes())

    if len(payload) < 8:
        raise ValueError("APK v3 payload is too small")

    schema = uint_from(payload[:4])
    if schema != ADB_SCHEMA_PACKAGE:
        raise ValueError(f"APK v3 file has unsupported schema: {schema:#x}")

    offset = 4
    if len(payload) - offset < 4:
        raise ValueError("APK v3 package has no ADB block")

    block_header = uint_from(payload[offset : offset + 4])
    offset += 4

    block_type = block_header >> 30
    block_size = block_header & 0x3FFFFFFF
    if block_type != ADB_BLOCK_ADB:
        raise ValueError(f"first APK v3 block is not ADB: type={block_type}")
    if block_size < 4:
        raise ValueError(f"invalid APK v3 ADB block size: {block_size}")

    block_payload_size = block_size - 4
    adb_payload_bounds(payload, offset, block_payload_size, "ADB block payload")
    adb_data = payload[offset : offset + block_payload_size]

    return parse_apk_v3_pkginfo_adb(adb_data, apk_file)


def parse_legacy_tar_apk_metadata(apk_file: Path) -> ApkMeta:
    with tarfile.open(apk_file, "r:*") as tar:
        for member in tar:
            if Path(member.name).name != ".PKGINFO":
                continue

            extracted = tar.extractfile(member)
            if extracted is None:
                break

            text = extracted.read().decode("utf-8", errors="replace")
            return parse_pkginfo(text, apk_file)

    raise ValueError("failed to find .PKGINFO")


def apk_metadata(apk_file: Path) -> ApkMeta:
    errors: list[str] = []

    try:
        return parse_apk_v3_metadata(apk_file)
    except Exception as e:
        errors.append(f"APK v3 parser: {e}")

    try:
        return parse_legacy_tar_apk_metadata(apk_file)
    except Exception as e:
        errors.append(f"legacy tar parser: {e}")

    die(f"failed to read apk metadata from {apk_file}: " + "; ".join(errors))


def apk_canonical_name(apk_file: Path, expected_arch: str) -> str:
    meta = apk_metadata(apk_file)

    if meta.arch not in {expected_arch, "noarch"}:
        die(
            f"package arch mismatch: {apk_file} has arch {meta.arch!r}, "
            f"but directory/profile arch is {expected_arch!r}"
        )

    return f"{meta.name}-{meta.version}{apk_file.suffix}"


def copy_file_if_changed(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)

    if dst.exists() and dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        return

    print(f"Updating {dst}")
    shutil.copy2(src, dst)


def remove_path(path: Path) -> None:
    if not path.exists():
        return

    print(f"Removing {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def copy_apk_repo_with_canonical_names(
    src_dir: Path,
    dst_dir: Path,
    expected_arch: str,
) -> None:
    apk_files = sorted(src_dir.glob(f"*.{PACKAGE_EXTENSION}"))

    if not apk_files:
        die(f"no apk packages found in: {src_dir}")

    remove_package_indexes(src_dir)

    src_by_canonical_name: dict[str, Path] = {}
    for src in apk_files:
        canonical_name = apk_canonical_name(src, expected_arch)
        if canonical_name in src_by_canonical_name:
            die(f"duplicate canonical package name: {canonical_name}")
        src_by_canonical_name[canonical_name] = src

    dst_dir.mkdir(parents=True, exist_ok=True)
    remove_package_indexes(dst_dir)

    expected_names = set(src_by_canonical_name)
    for child in sorted(dst_dir.iterdir(), key=lambda p: p.name):
        if child.name not in expected_names:
            remove_path(child)

    for canonical_name, src in sorted(src_by_canonical_name.items()):
        copy_file_if_changed(src, dst_dir / canonical_name)

    remove_package_indexes(dst_dir)


def sync_router_packages(
    cfg: ConfigData,
    router: RouterDef,
    version: str,
) -> None:
    profile = router_device_profile(cfg, router)
    src_dir = package_source_dir_from_profile(version, profile)
    dst_dir = router.path / ROUTER_PACKAGES_DIRNAME
    arch = profile_arch(profile)

    if not src_dir.is_dir():
        die(f"package source directory does not exist: {src_dir}")

    remove_package_indexes(src_dir)

    if sorted(src_dir.glob("*.ipk")):
        die(
            f"ipk packages are not supported; "
            f"OpenWrt >= {MIN_OPENWRT_VERSION_TEXT} uses apk here: {src_dir}"
        )

    copy_apk_repo_with_canonical_names(src_dir, dst_dir, arch)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Sync common router files from routers/example to routers "
            "defined in config.json"
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to config.json (default: config.json)",
    )
    ap.add_argument(
        "--no-clear",
        action="store_true",
        help="do not clear screen before output",
    )
    ap.add_argument(
        "--skip-awg-download",
        action="store_true",
        help="do not download AWG packages from GitHub releases",
    )
    ap.add_argument(
        "--skip-package-sync",
        action="store_true",
        help="do not copy per-router apk package repositories",
    )
    ap.add_argument(
        "--skip-hooks",
        action="store_true",
        help=(
            "do not run tools/generate.py, tools/ensure_ssh_keys.py, "
            "tools/validate.py and tools/show_unmanaged.py"
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help=(
            "pass --force to tools/generate.py and regenerate mesh/exit "
            "WireGuard/AmneziaWG keys; access secrets are preserved"
        ),
    )

    args = ap.parse_args()

    cfg = load_json_config(Path(args.config))
    cfg_data = build_config_data(cfg)
    routers = cfg_data.routers
    ensure_example_router_dir()

    if not routers:
        die("no routers defined in config")

    clear_screen(not args.no_clear)

    for router in routers:
        ensure_router_from_example(EXAMPLE_ROUTER_DIR, router)

    if not args.skip_awg_download:
        ensure_awg_packages(cfg_data, routers, cfg_data.openwrt_version)

    if not args.skip_package_sync:
        for router in routers:
            sync_router_packages(cfg_data, router, cfg_data.openwrt_version)

    for router in routers:
        sync_router(EXAMPLE_ROUTER_DIR, router)

    if not args.skip_hooks:
        config_arg = str(Path(args.config))

        generate_args = ["--config", config_arg]
        if args.force:
            generate_args.append("--force")

        run_python_main("tools.generate", generate_args)
        run_python_main("tools.ensure_ssh_keys", ["--config", config_arg])
        run_python_main("tools.validate", ["--config", config_arg])
        run_python_main("tools.show_unmanaged", ["--config", config_arg])


if __name__ == "__main__":
    main()
