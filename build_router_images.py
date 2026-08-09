#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ImageBuilderSpec:
    target: str
    subtarget: str
    directory_name: str
    archive_path: Path
    download_url: str

    @property
    def key(self) -> tuple[str, str]:
        return self.target, self.subtarget


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


def imagebuilder_spec(profile: DeviceProfile, version: str) -> ImageBuilderSpec:
    directory_name = (
        f"openwrt-imagebuilder-{version}"
        f"-{profile.target}-{profile.subtarget}.Linux-x86_64"
    )
    archive_path = Path("imagebuilders") / f"{directory_name}.tar.zst"
    download_url = (
        f"{OPENWRT_RELEASE_BASE_URL}/{version}"
        f"/targets/{profile.target}/{profile.subtarget}/{archive_path.name}"
    )
    return ImageBuilderSpec(
        target=profile.target,
        subtarget=profile.subtarget,
        directory_name=directory_name,
        archive_path=archive_path,
        download_url=download_url,
    )


def collect_imagebuilders(
    cfg: ConfigData,
    routers: list[RouterDef],
    version: str,
) -> dict[tuple[str, str], ImageBuilderSpec]:
    builders: dict[tuple[str, str], ImageBuilderSpec] = {}

    for router in routers:
        spec = imagebuilder_spec(router_profile(cfg, router), version)
        builders.setdefault(spec.key, spec)

    return builders


def prepare_imagebuilders(
    builders: dict[tuple[str, str], ImageBuilderSpec],
) -> None:
    print()
    print("=== Preparing OpenWrt ImageBuilders ===")

    for spec in builders.values():
        print(f"{spec.target}/{spec.subtarget}:")
        if spec.archive_path.exists():
            if not spec.archive_path.is_file():
                die(f"ImageBuilder archive path is not a file: {spec.archive_path}")
            if spec.archive_path.stat().st_size == 0:
                spec.archive_path.unlink()
            else:
                print(f"  Cached: {spec.archive_path}")
                continue

        print(f"  Downloading: {spec.download_url}")
        download_file(spec.download_url, spec.archive_path)
        print(f"  Ready: {spec.archive_path}")


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


def validate_router_build_inputs(router: RouterDef) -> None:
    router_dir = ROUTERS_ROOT / router.slug
    files_dir = router_dir / ROUTER_FILES_DIRNAME
    packages_dir = router_dir / ROUTER_PACKAGES_DIRNAME

    if not router_dir.is_dir():
        die(f"missing router directory: {router_dir}")
    if not files_dir.is_dir():
        die(f"missing directory: {files_dir}")
    if not packages_dir.is_dir():
        die(f"missing directory: {packages_dir}. Run ./generate_configs.py first")


def build_router(
    cfg: ConfigData,
    router: RouterDef,
    version: str,
    config_path: Path,
    imagebuilder: ImageBuilderSpec,
) -> None:
    name = router.name
    slug = router.slug
    router_dir = ROUTERS_ROOT / slug
    files_dir = router_dir / ROUTER_FILES_DIRNAME
    packages_dir = router_dir / ROUTER_PACKAGES_DIRNAME

    profile = router_profile(cfg, router)
    router_tmp = profile.name
    board = profile.board
    arch = profile.arch
    vendor_tmp = profile.target
    device_tmp = profile.subtarget
    openwrt_version_part = version

    if imagebuilder.key != (vendor_tmp, device_tmp):
        die(f"wrong ImageBuilder selected for router: {name}")
    if not imagebuilder.archive_path.is_file():
        die(f"missing ImageBuilder archive: {imagebuilder.archive_path}")

    print()
    print(f"=== {name} / {router_tmp} ===")
    print(f"Board: {board}")
    print(f"Arch: {arch}")
    print(f"Packages: {packages_dir}")
    print(f"ImageBuilder: {imagebuilder.archive_path}")

    build_dir = router_dir / imagebuilder.directory_name

    if not build_dir.is_dir():
        sh(["tar", "-xf", str(imagebuilder.archive_path), "-C", str(router_dir)])

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

    print(f"Images for {name}:")
    for result_path in copied_images:
        print(f"  {result_path}")

    for child in router_dir.glob("openwrt-imagebuilder-*"):
        if child.is_dir():
            shutil.rmtree(child)


def build_failure_text(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        return f"terminated with exit status {exc.code}"
    return str(exc) or type(exc).__name__


def build_routers_parallel(
    cfg: ConfigData,
    routers: list[RouterDef],
    version: str,
    config_path: Path,
    builders: dict[tuple[str, str], ImageBuilderSpec],
    jobs: int,
) -> None:
    worker_count = min(jobs, len(routers))
    print()
    print(f"=== Building {len(routers)} router image(s), jobs={worker_count} ===")

    failures: list[tuple[RouterDef, BaseException]] = []
    futures: dict[Future[None], RouterDef] = {}

    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="openwrt-image",
    ) as executor:
        for router in routers:
            profile = router_profile(cfg, router)
            imagebuilder = builders[(profile.target, profile.subtarget)]
            future = executor.submit(
                build_router,
                cfg,
                router,
                version,
                config_path,
                imagebuilder,
            )
            futures[future] = router

        for future in as_completed(futures):
            router = futures[future]
            try:
                future.result()
            except (Exception, SystemExit) as exc:
                failures.append((router, exc))
            else:
                print(f"=== Completed: {router.name} ===")

    if failures:
        print(file=sys.stderr)
        print("Failed router builds:", file=sys.stderr)
        for router, exc in failures:
            print(f"  {router.name}: {build_failure_text(exc)}", file=sys.stderr)
        raise SystemExit(1)


def positive_jobs(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def default_jobs(router_count: int) -> int:
    return min(router_count, max(1, os.cpu_count() or 1))


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
    parser.add_argument(
        "-j",
        "--jobs",
        type=positive_jobs,
        default=None,
        help=(
            "number of router images to build in parallel "
            "(default: min(selected routers, CPU count); use 1 for sequential builds)"
        ),
    )

    args = parser.parse_args()

    config_path = Path(args.config)
    cfg_data = load_config(config_path)
    version = config_version(cfg_data, args.version)

    routers = cfg_data.routers
    router_names = parse_csv_names(args.routers)
    if router_names:
        routers = [find_router(cfg_data, name) for name in router_names]

    if not routers:
        die("no routers selected")

    for router in routers:
        validate_router_build_inputs(router)

    builders = collect_imagebuilders(cfg_data, routers, version)
    prepare_imagebuilders(builders)

    jobs = args.jobs if args.jobs is not None else default_jobs(len(routers))
    build_routers_parallel(
        cfg_data,
        routers,
        version,
        config_path,
        builders,
        jobs,
    )


if __name__ == "__main__":
    main()
