#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import shutil
from datetime import datetime
from pathlib import Path

from tools.cli_common import (
    die,
    load_json_config,
    parse_csv_names,
    run_checked,
    run_no_capture,
)
from tools.router_order import router_slug
from tools.common import build_config_data
from tools.default import (
    CONFIG_KEY_ACCESS,
    CONFIG_KEY_NAME,
    CONFIG_KEY_PACKAGES,
    CONFIG_KEY_PROTOCOL,
    CONFIG_PATH,
    IMAGES_DIR,
    INSTALL_IMAGE_TYPES,
    MIN_OPENWRT_VERSION,
    MIN_OPENWRT_VERSION_TEXT,
    OPENWRT_RELEASE_BASE_URL,
    ROUTER_FILES_DIRNAME,
    ROUTER_REQUIRED_ACCESS_PACKAGES,
    ROUTER_REQUIRED_PACKAGES,
    ROUTERS_ROOT,
    ROUTER_PACKAGES_DIRNAME,
)


def sh(args: list[str], cwd: Path | None = None) -> None:
    run_no_capture(args, cwd=cwd)


def out(args: list[str], cwd: Path | None = None) -> str:
    return run_checked(args, cwd=cwd).strip()


def load_config(config_path: Path) -> dict[str, object]:
    cfg = load_json_config(config_path)
    build_config_data(cfg)
    return cfg


def validate_packages_list(
    value: object, where: str, *, allow_empty: bool
) -> list[str]:
    if value is None:
        return []

    if not isinstance(value, list):
        die(f"{where} must be a list of strings")

    if not value and not allow_empty:
        die(f"{where} must be a non-empty list of strings")

    out: list[str] = []
    seen: set[str] = set()

    for item in value:
        if not isinstance(item, str) or not item:
            die(f"{where} must be a list of non-empty strings")
        if item in seen:
            die(f"{where}: duplicate package entry: {item}")
        seen.add(item)
        out.append(item)

    return out


def dedupe_packages(packages: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for package in packages:
        if package in seen:
            continue
        result.append(package)
        seen.add(package)

    return result


def config_packages(cfg: dict) -> list[str]:
    packages = validate_packages_list(
        cfg.get(CONFIG_KEY_PACKAGES),
        "config packages",
        allow_empty=True,
    )

    for package in packages:
        if package[0] in "+-":
            die(f"global packages must not start with + or -: {package}")

    return packages


def required_router_packages(cfg: dict, router_name: str) -> list[str]:
    packages = list(ROUTER_REQUIRED_PACKAGES)

    access = cfg.get(CONFIG_KEY_ACCESS, {})
    if access is None:
        access = {}
    if not isinstance(access, dict):
        die("config key 'access' must be an object")

    groups = access.get(router_name, [])
    if groups is None:
        groups = []
    if not isinstance(groups, list):
        die(f"access[{router_name}] must be a list")

    for idx, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            die(f"access[{router_name}][{idx}] must be an object")
        protocol = group.get(CONFIG_KEY_PROTOCOL)
        if not isinstance(protocol, str):
            die(f"access[{router_name}][{idx}].protocol must be a string")
        try:
            packages.extend(ROUTER_REQUIRED_ACCESS_PACKAGES[protocol])
        except KeyError:
            die(f"access[{router_name}][{idx}].protocol: unknown protocol: {protocol}")

    return dedupe_packages(packages)


def router_packages(cfg: dict, router: dict) -> list[str]:
    name = router.get(CONFIG_KEY_NAME, "<unknown>")
    if not isinstance(name, str) or not name:
        die("router name must be a non-empty string")

    required = required_router_packages(cfg, name)
    base = required + config_packages(cfg)

    overrides = validate_packages_list(
        router.get(CONFIG_KEY_PACKAGES),
        f"router {name}.packages",
        allow_empty=True,
    )

    result = dedupe_packages(base)
    present = set(result)
    required_set = set(required)

    for entry in overrides:
        if len(entry) < 2 or entry[0] not in "+-":
            die(f"router {name}.packages entry must start with + or -: {entry}")

        op = entry[0]
        package = entry[1:]

        if not package:
            die(f"router {name}.packages has empty package entry: {entry}")

        if op == "+":
            if package not in present:
                result.append(package)
                present.add(package)
            continue

        if package in required_set:
            die(
                f"router {name}.packages tries to remove required managed "
                f"package: {package}"
            )

        if package not in present:
            die(
                f"router {name}.packages tries to remove package "
                f"that is not currently installed: {package}"
            )

        result = [p for p in result if p != package]
        present.remove(package)

    return result


def config_version(cfg: dict, override: str | None) -> str:
    version = override or cfg.get("openwrt_version")

    if not isinstance(version, str) or not version:
        die("config openwrt_version must be a non-empty string")

    parts = version.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        die(f"OpenWrt version must be numeric and >= {MIN_OPENWRT_VERSION_TEXT}")

    if (major, minor) < MIN_OPENWRT_VERSION:
        die(f"OpenWrt version must be >= {MIN_OPENWRT_VERSION_TEXT}")

    return version


def git_short() -> str:
    try:
        return out(["git", "rev-parse", "--short", "HEAD"])
    except Exception:
        return "unknown"


def find_router(cfg: dict, name: str) -> dict:
    routers = cfg.get("routers")
    if not isinstance(routers, list):
        die("config key 'routers' must be a list")

    for router in routers:
        if isinstance(router, dict) and router.get("name", "").lower() == name.lower():
            return router

    die(f"unknown router: {name}")


def router_profile(cfg: dict, router: dict) -> tuple[str, dict]:
    name = router.get("name")
    profile_name = router.get("device_profile")

    if not isinstance(name, str) or not name:
        die("router.name must be a non-empty string")

    if not isinstance(profile_name, str) or not profile_name:
        die(f"router {name} has no device_profile")

    profiles = cfg.get("device_profiles")
    if not isinstance(profiles, dict):
        die("config key 'device_profiles' must be an object")

    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        die(f"unknown device_profile for {name}: {profile_name}")

    return profile_name, profile


def board_arch_from_profile(profile: dict) -> tuple[str, str, str, str]:
    board = profile.get("board")
    arch = profile.get("arch")

    if not isinstance(board, str) or not board or "/" not in board:
        die("device_profile.board must be like 'target/subtarget'")

    if not isinstance(arch, str) or not arch:
        die("device_profile.arch must be a non-empty string")

    vendor_tmp, device_tmp = board.split("/", 1)

    if not vendor_tmp or not device_tmp:
        die("device_profile.board must be like 'target/subtarget'")

    return board, arch, vendor_tmp, device_tmp


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


def build_router(cfg: dict, router: dict, version: str, config_path: Path) -> None:
    name = router.get("name")
    if not isinstance(name, str) or not name:
        die("router.name must be a non-empty string")

    slug = router_slug(name)
    router_dir = ROUTERS_ROOT / slug

    if not router_dir.is_dir():
        die(f"missing router directory: {router_dir}")

    files_dir = router_dir / ROUTER_FILES_DIRNAME
    packages_dir = router_dir / ROUTER_PACKAGES_DIRNAME

    if not files_dir.is_dir():
        die(f"missing directory: {files_dir}")

    if not packages_dir.is_dir():
        die(f"missing directory: {packages_dir}. Run ./generate_configs.py first")

    profile_name, profile = router_profile(cfg, router)
    router_tmp = profile_name
    board, arch, vendor_tmp, device_tmp = board_arch_from_profile(profile)

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
    print(f"=== {name} / {profile_name} ===")
    print(f"Board: {board}")
    print(f"Arch: {arch}")
    print(f"Packages: {packages_dir}")
    print(f"Downloading from: {dl_url}")

    if not dl_local.exists():
        sh(["wget", "-q", "-O", str(dl_local), dl_url])

    build_dir = router_dir / file_name_tmp

    if not build_dir.is_dir():
        sh(["tar", "-xf", str(dl_local), "-C", str(router_dir)])

    shutil.rmtree(build_dir / ROUTER_FILES_DIRNAME, ignore_errors=True)
    shutil.rmtree(build_dir / ROUTER_PACKAGES_DIRNAME, ignore_errors=True)

    staged_files = build_dir / ROUTER_FILES_DIRNAME
    staged_packages = build_dir / ROUTER_PACKAGES_DIRNAME

    shutil.copytree(files_dir, staged_files)
    shutil.copytree(packages_dir, staged_packages)

    run_no_capture(
        [
            "./tools/secrets.py",
            "--config",
            str(config_path),
            "decrypt-tree",
            str(staged_files),
        ]
    )
    run_no_capture(["./tools/secrets.py", "assert-no-markers", str(staged_files)])

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
            "router names, for example: RouterA RouterB or RouterA,RouterB. "
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
    cfg = load_config(config_path)
    version = config_version(cfg, args.version)

    routers = cfg.get("routers")
    if not isinstance(routers, list):
        die("config key 'routers' must be a list")

    router_names = parse_csv_names(args.routers)
    if router_names:
        routers = [find_router(cfg, name) for name in router_names]

    for router in routers:
        if not isinstance(router, dict):
            die("each router entry must be an object")
        build_router(cfg, router, version, config_path)


if __name__ == "__main__":
    main()
