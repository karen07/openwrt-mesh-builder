#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

from tools.cli_common import clear_screen
from tools.config_io import load_json_config
from tools.process import die, run_checked, run_no_capture
from tools.common import ConfigData, DeviceProfile, RouterDef, build_config_data
from tools.default import (
    CONFIG_PATH,
    AWG_PACKAGE_NAMES,
    AWG_RELEASE_BASE_URL,
    MIN_OPENWRT_VERSION_TEXT,
    PACKAGE_EXTENSION,
    PACKAGE_SOURCE_ROOT,
    ROUTER_EXAMPLE_DIR as EXAMPLE_ROUTER_DIR,
    ROUTER_PACKAGES_DIRNAME,
)
from tools.sync_rules import ensure_router_from_example, sync_router
from tools.ensure_ssh_keys import main as ensure_ssh_keys_main
from tools.generate import main as generate_main
from tools.show_unmanaged import main as show_unmanaged_main
from tools.validate import main as validate_main
from tools.downloads import try_download_file
from tools.file_ops import copy_file_if_changed, remove_path
from tools.packages import apk_canonical_name, remove_package_indexes


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


def router_device_profile(cfg: ConfigData, router: RouterDef) -> DeviceProfile:
    return cfg.device_profiles[router.device_profile]


def profile_arch(profile: DeviceProfile) -> str:
    return profile.arch


def profile_board_arch(profile: DeviceProfile) -> tuple[str, str, str, str]:
    return profile.board, profile.arch, profile.target, profile.subtarget


def package_source_dir_from_profile(version: str, profile: DeviceProfile) -> Path:
    return PACKAGE_SOURCE_ROOT / version / profile.board / profile.arch


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

        if not try_download_file(url, tmp_dst):
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

        generate_main(generate_args)
        ensure_ssh_keys_main(["--config", config_arg])
        validate_main(["--config", config_arg])
        show_unmanaged_main(["--config", config_arg])


if __name__ == "__main__":
    main()
