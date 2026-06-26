#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import shutil
from datetime import datetime
from pathlib import Path

from tools.cli_common import parse_csv_names
from tools.config_io import load_json_config
from tools.process import die, run_checked, run_no_capture
from tools.common import (
    ConfigData,
    DeviceProfile,
    RouterDef,
    build_config_data,
    normalize_openwrt_version,
)
from tools.package_model import managed_router_packages
from tools.secrets import assert_no_markers, decrypt_tree
from tools.downloads import download_file
from tools.git_utils import git_short
from tools.default import (
    CONFIG_PATH,
    IMAGES_DIR,
    INSTALL_IMAGE_TYPES,
    MIN_OPENWRT_VERSION_TEXT,
    OPENWRT_RELEASE_BASE_URL,
    ROUTER_FILES_DIRNAME,
    ROUTERS_ROOT,
    ROUTER_PACKAGES_DIRNAME,
)


def sh(args: list[str], cwd: Path | None = None) -> None:
    run_no_capture(args, cwd=cwd)


def out(args: list[str], cwd: Path | None = None) -> str:
    return run_checked(args, cwd=cwd).strip()


def load_config(config_path: Path) -> ConfigData:
    return build_config_data(load_json_config(config_path))


def router_packages(cfg: ConfigData, router: RouterDef) -> list[str]:
    return managed_router_packages(cfg, router)


def config_version(cfg_data: ConfigData, override: str | None) -> str:
    if override is None:
        return cfg_data.openwrt_version
    return normalize_openwrt_version(override, "--version")


def find_router(cfg: ConfigData, name: str) -> RouterDef:
    for router in cfg.routers:
        if router.name.lower() == name.lower():
            return router

    die(f"unknown router: {name}")


def router_profile(cfg: ConfigData, router: RouterDef) -> DeviceProfile:
    return cfg.device_profiles[router.device_profile]


def normalize_install_image_type(raw_type: str) -> str | None:
    name = raw_type.lower()

    for image_type in INSTALL_IMAGE_TYPES:
        if image_type in name:
            return image_type

    return None


def collect_router_install_images(
    bin_dir: Path,
    *,
    openwrt_version_part: str,
    vendor_tmp: str,
    device_tmp: str,
    router_tmp: str,
) -> list[tuple[Path, str]]:
    prefix = f"openwrt-{openwrt_version_part}-{vendor_tmp}-{device_tmp}-{router_tmp}-"
    images: list[tuple[Path, str]] = []
    seen_types: set[str] = set()

    for image_path in sorted(bin_dir.glob(f"{prefix}*")):
        if not image_path.is_file():
            continue

        raw_name = image_path.name[len(prefix) :]
        image_type = normalize_install_image_type(raw_name)

        if image_type is None:
            continue

        if image_type in seen_types:
            die(
                f"duplicate {image_type} image for {router_tmp}. "
                f"Refusing to overwrite result image names."
            )

        seen_types.add(image_type)
        images.append((image_path, image_type))

    if not images:
        die(
            f"no factory/sysupgrade images found for profile {router_tmp} in: {bin_dir}"
        )

    return images


def build_router(
    cfg: ConfigData,
    router: RouterDef,
    version: str,
    config_path: Path,
) -> None:
    name = router.name
    slug = router.slug
    router_dir = ROUTERS_ROOT / slug

    if not router_dir.is_dir():
        die(f"missing router directory: {router_dir}")

    files_dir = router_dir / ROUTER_FILES_DIRNAME
    packages_dir = router_dir / ROUTER_PACKAGES_DIRNAME

    if not files_dir.is_dir():
        die(f"missing directory: {files_dir}")

    if not packages_dir.is_dir():
        die(f"missing directory: {packages_dir}. Run ./generate_configs.py first")

    profile = router_profile(cfg, router)
    router_tmp = profile.name
    board = profile.board
    arch = profile.arch
    vendor_tmp = profile.target
    device_tmp = profile.subtarget

    base_url = f"{OPENWRT_RELEASE_BASE_URL}/{version}"
    file_name_tmp = (
        f"openwrt-imagebuilder-{version}" f"-{vendor_tmp}-{device_tmp}.Linux-x86_64"
    )
    openwrt_version_part = version
    dl_path = f"{base_url}/targets/{vendor_tmp}/{device_tmp}"
    dl_file = f"{file_name_tmp}.tar.zst"
    dl_url = f"{dl_path}/{dl_file}"
    dl_local = Path(dl_file)

    print()
    print(f"=== {name} / {router_tmp} ===")
    print(f"Board: {board}")
    print(f"Arch: {arch}")
    print(f"Packages: {packages_dir}")
    print(f"Downloading from: {dl_url}")

    if not dl_local.exists():
        download_file(dl_url, dl_local)

    build_dir = router_dir / file_name_tmp

    if not build_dir.is_dir():
        sh(["tar", "-xf", str(dl_local), "-C", str(router_dir)])

    shutil.rmtree(build_dir / ROUTER_FILES_DIRNAME, ignore_errors=True)
    shutil.rmtree(build_dir / ROUTER_PACKAGES_DIRNAME, ignore_errors=True)

    staged_files = build_dir / ROUTER_FILES_DIRNAME
    staged_packages = build_dir / ROUTER_PACKAGES_DIRNAME

    shutil.copytree(files_dir, staged_files)
    shutil.copytree(packages_dir, staged_packages)

    decrypt_tree([staged_files], config_path=config_path)
    assert_no_markers([staged_files])

    etc_dir = staged_files / "etc"
    etc_dir.mkdir(parents=True, exist_ok=True)

    git = git_short()

    deploy_time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    (etc_dir / "deploy_version").write_text(
        f"OpenWrt {openwrt_version_part} {git} {deploy_time}\n",
        encoding="utf-8",
    )

    result_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    sh(
        [
            "make",
            "image",
            f"PROFILE={router_tmp}",
            f"PACKAGES={' '.join(router_packages(cfg, router))}",
            f"FILES={ROUTER_FILES_DIRNAME}",
        ],
        cwd=build_dir,
    )

    bin_dir = build_dir / "bin" / "targets" / vendor_tmp / device_tmp
    images = collect_router_install_images(
        bin_dir,
        openwrt_version_part=openwrt_version_part,
        vendor_tmp=vendor_tmp,
        device_tmp=device_tmp,
        router_tmp=router_tmp,
    )

    IMAGES_DIR.mkdir(exist_ok=True)

    copied_images: list[Path] = []
    for image_path, image_type in images:
        result_name = (
            f"{slug}_{openwrt_version_part}_{git}_{result_time}_{image_type}.bin"
        )
        result_path = IMAGES_DIR / result_name
        shutil.copy2(image_path, result_path)
        copied_images.append(result_path)

    print("Images:")
    for result_path in copied_images:
        print(f"  {result_path}")

    for child in router_dir.glob("openwrt-imagebuilder-*"):
        if child.is_dir():
            shutil.rmtree(child)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build OpenWrt images for selected routers or all routers"
    )
    parser.add_argument(
        "routers",
        nargs="*",
        help=(
            "router names, for example: Spine01 Leaf01 or Spine01,Leaf01. "
            "If omitted or set to 'all', builds all routers"
        ),
    )
    parser.add_argument(
        "--version",
        default=None,
        help=(
            f"OpenWrt version, for example {MIN_OPENWRT_VERSION_TEXT}.4. "
            f"Default: config openwrt_version; must be >= {MIN_OPENWRT_VERSION_TEXT}"
        ),
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )

    args = parser.parse_args()

    config_path = Path(args.config)
    cfg_data = load_config(config_path)
    version = config_version(cfg_data, args.version)

    routers = cfg_data.routers
    router_names = parse_csv_names(args.routers)
    if router_names:
        routers = [find_router(cfg_data, name) for name in router_names]

    for router in routers:
        build_router(cfg_data, router, version, config_path)


if __name__ == "__main__":
    main()
