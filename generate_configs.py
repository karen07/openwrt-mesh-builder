#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import filecmp
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from tools.cli_common import (
    clear_screen,
    die,
    load_json_config,
    run_checked,
    run_no_capture,
)
from tools.router_order import RouterDef, load_routers
from tools.common import build_config_data, validate_config_known_keys
from tools.default import (
    CONFIG_PATH,
    AWG_PACKAGE_NAMES,
    AWG_RELEASE_BASE_URL,
    LOCAL_TEMP_ROOT,
    MIN_OPENWRT_VERSION,
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


def run(
    args: list[str],
    cwd: Path | None = None,
    quiet: bool = False,
) -> None:
    if quiet:
        run_checked(args, cwd=cwd, quiet=True)
    else:
        run_no_capture(args, cwd=cwd)


def out(
    args: list[str],
    cwd: Path | None = None,
    quiet: bool = False,
) -> str:
    return run_checked(args, cwd=cwd, quiet=quiet).strip()


def ensure_example_router_dir() -> None:
    if not EXAMPLE_ROUTER_DIR.is_dir():
        die(f"missing example router directory: {EXAMPLE_ROUTER_DIR}")


def ensure_apk_tool() -> None:
    if shutil.which("apk") is None:
        die("missing apk tool. On Arch Linux install it with: sudo pacman -S apk-tools")


def validate_openwrt_version(version: object) -> str:
    if not isinstance(version, str) or not version:
        die("config openwrt_version must be a non-empty string")

    parts = version.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        die(f"OpenWrt version must be numeric and >= {MIN_OPENWRT_VERSION_TEXT}")

    if (major, minor) < MIN_OPENWRT_VERSION:
        die(
            f"OpenWrt version must be >= {MIN_OPENWRT_VERSION_TEXT} for AWG2/apk-only builds"
        )

    return version


def router_device_profile(
    cfg: dict[str, object],
    router: RouterDef,
) -> dict[str, object]:
    raw_routers = cfg.get("routers")
    if not isinstance(raw_routers, list):
        die("config key 'routers' must be a list")

    profile_name = None

    for item in raw_routers:
        if not isinstance(item, dict):
            continue
        if item.get("name") == router.name:
            profile_name = item.get("device_profile")
            break

    if not isinstance(profile_name, str) or not profile_name:
        die(f"router {router.name} has no device_profile")

    raw_profiles = cfg.get("device_profiles")
    if not isinstance(raw_profiles, dict):
        die("config key 'device_profiles' must be an object")

    profile = raw_profiles.get(profile_name)
    if not isinstance(profile, dict):
        die(f"unknown device_profile for {router.name}: {profile_name}")

    return profile


def profile_arch(profile: dict[str, object]) -> str:
    arch = profile.get("arch")

    if not isinstance(arch, str) or not arch:
        die("device_profile.arch must be a non-empty string")

    return arch


def package_source_dir_from_profile(
    cfg: dict[str, object],
    profile: dict[str, object],
) -> Path:
    version = validate_openwrt_version(cfg.get("openwrt_version"))
    board = profile.get("board")
    arch = profile.get("arch")

    if not isinstance(board, str) or not board or "/" not in board:
        die("device_profile.board must be like 'target/subtarget'")

    if not isinstance(arch, str) or not arch:
        die("device_profile.arch must be a non-empty string")

    target, subtarget = board.split("/", 1)
    if not target or not subtarget:
        die("device_profile.board must be like 'target/subtarget'")

    return PACKAGE_SOURCE_ROOT / version / board / arch


def remove_package_indexes(package_dir: Path) -> None:
    for name in PACKAGE_REPO_INDEX_FILES:
        path = package_dir / name
        if path.exists():
            path.unlink()


def download_binary(url: str, dst: Path) -> bool:
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.unlink(missing_ok=True)

    try:
        with urllib.request.urlopen(url, timeout=60) as response:
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
    cfg: dict[str, object],
    profile: dict[str, object],
) -> None:
    version = validate_openwrt_version(cfg.get("openwrt_version"))
    board = profile.get("board")
    arch = profile.get("arch")

    if not isinstance(board, str) or not board or "/" not in board:
        die("device_profile.board must be like 'target/subtarget'")

    if not isinstance(arch, str) or not arch:
        die("device_profile.arch must be a non-empty string")

    target, subtarget = board.split("/", 1)
    if not target or not subtarget:
        die("device_profile.board must be like 'target/subtarget'")

    dst_dir = package_source_dir_from_profile(cfg, profile)
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


def ensure_awg_packages(cfg: dict[str, object], routers: list[RouterDef]) -> None:
    seen: set[tuple[str, str]] = set()

    for router in routers:
        profile = router_device_profile(cfg, router)

        board = profile.get("board")
        arch = profile.get("arch")

        if not isinstance(board, str) or not isinstance(arch, str):
            die(f"router {router.name} has invalid device_profile")

        key = (board, arch)
        if key in seen:
            continue

        seen.add(key)
        ensure_named_awg_packages_for_profile(cfg, profile)


def parse_adbdump_packages(text: str) -> list[ApkMeta]:
    result: list[ApkMeta] = []

    name: str | None = None
    version: str | None = None
    arch: str | None = None

    def flush() -> None:
        nonlocal name, version, arch

        if name is not None:
            if not version or not arch:
                die(f"incomplete apk metadata for package: {name}")

            result.append(ApkMeta(name=name, version=version, arch=arch))

        name = None
        version = None
        arch = None

    for line in text.splitlines():
        line = line.strip()

        if line.startswith("- name: "):
            flush()
            name = line.removeprefix("- name: ").strip()
            continue

        if line.startswith("version: ") and name:
            version = line.removeprefix("version: ").strip()
            continue

        if line.startswith("arch: ") and name:
            arch = line.removeprefix("arch: ").strip()
            continue

    flush()
    return result


def apk_index_packages(apk_files: list[Path], index_path: Path) -> None:
    if not apk_files:
        die(f"no apk packages found for index: {index_path.parent}")

    run(
        ["apk", "mkndx", "--allow-untrusted", "--output", index_path.name]
        + [p.name for p in apk_files],
        cwd=index_path.parent,
        quiet=True,
    )


def apk_metadata(apk_file: Path) -> ApkMeta:
    with tempfile.TemporaryDirectory(
        prefix=".apk-meta-",
        dir=LOCAL_TEMP_ROOT,
    ) as tmp_raw:
        tmp_dir = Path(tmp_raw)
        tmp_apk = tmp_dir / apk_file.name
        shutil.copy2(apk_file, tmp_apk)

        index_path = tmp_dir / "packages.adb"
        apk_index_packages([tmp_apk], index_path)

        dump = out(["apk", "adbdump", index_path.name], cwd=tmp_dir, quiet=True)
        packages = parse_adbdump_packages(dump)

        if len(packages) != 1:
            die(f"failed to parse apk metadata from: {apk_file}")

        return packages[0]


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


def sync_router_packages(cfg: dict[str, object], router: RouterDef) -> None:
    profile = router_device_profile(cfg, router)
    src_dir = package_source_dir_from_profile(cfg, profile)
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

    ensure_apk_tool()
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
    validate_config_known_keys(cfg)
    build_config_data(cfg)
    routers = load_routers(cfg)
    ensure_example_router_dir()

    if not routers:
        die("no routers defined in config")

    clear_screen(not args.no_clear)

    for router in routers:
        ensure_router_from_example(EXAMPLE_ROUTER_DIR, router)

    if not args.skip_awg_download:
        ensure_awg_packages(cfg, routers)

    if not args.skip_package_sync:
        for router in routers:
            sync_router_packages(cfg, router)

    for router in routers:
        sync_router(EXAMPLE_ROUTER_DIR, router)

    if not args.skip_hooks:
        config_arg = str(Path(args.config))

        generate_args = ["./tools/generate.py", "--config", config_arg]
        if args.force:
            generate_args.append("--force")

        run(generate_args)
        run(["./tools/ensure_ssh_keys.py", "--config", config_arg])
        run(["./tools/validate.py", "--config", config_arg])
        run(["./tools/show_unmanaged.py", "--config", config_arg])


if __name__ == "__main__":
    main()
