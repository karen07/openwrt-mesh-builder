#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import shlex
from pathlib import Path

from tools.cli_common import (
    ask_yes_no,
    clear_screen,
    die,
    load_json_config,
    parse_csv_names,
    run_ssh,
    scp_to_host,
)
from tools.router_order import RouterDef, build_router_order, router_slug
from tools.default import (
    CONFIG_PATH,
    SCP_TIMEOUT,
    SSH_TIMEOUT,
    ASYNC_SYSUPGRADE_DELAY_SEC,
    INSTALL_IMAGE_TYPE_SYSUPGRADE,
    IMAGES_DIR as RESULT_DIR,
    REMOTE_UPLOAD_DIR,
)


def scp_to_router(
    local_path: Path,
    router: RouterDef,
    remote_dir: str,
    scp_timeout: int,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[int, str, str]:
    return scp_to_host(
        local_path=local_path,
        remote_host=router.ssh_host,
        remote_dir=remote_dir,
        scp_timeout=scp_timeout,
        config_path=config_path,
    )


def find_image_for_router(
    result_dir: Path, router: RouterDef, git_version: str
) -> Path:
    slug = router_slug(router.name)
    sysupgrade_pattern = f"{slug}_*_{git_version}_*_{INSTALL_IMAGE_TYPE_SYSUPGRADE}.bin"
    matches = sorted(p for p in result_dir.glob(sysupgrade_pattern) if p.is_file())

    if not matches:
        any_pattern = f"{slug}_*_{git_version}_*.bin"
        other_images = sorted(
            p.name for p in result_dir.glob(any_pattern) if p.is_file()
        )
        hint = ""
        if other_images:
            hint = "; found only non-sysupgrade images: " + ", ".join(other_images)
        raise FileNotFoundError(
            f"no sysupgrade image found for router={router.name} "
            f"git_version={git_version} pattern={sysupgrade_pattern}{hint}"
        )

    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise RuntimeError(
            f"multiple sysupgrade images found for router={router.name}: {names}"
        )

    return matches[0]


def copy_images(
    routers: list[RouterDef],
    git_version: str,
    result_dir: Path,
    remote_dir: str,
    scp_timeout: int,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[dict[str, Path], dict[str, str]]:
    copied: dict[str, Path] = {}
    failed: dict[str, str] = {}

    for router in routers:
        print(f"{router.name} ({router.ssh_host})")

        try:
            image_path = find_image_for_router(result_dir, router, git_version)
            print(f"  image: {image_path.name}")
        except Exception as e:
            failed[router.name] = str(e)
            print(f"  FAIL: {e}")
            print()
            continue

        rc, _out, err = scp_to_router(
            local_path=image_path,
            router=router,
            remote_dir=remote_dir,
            scp_timeout=scp_timeout,
            config_path=config_path,
        )

        if rc != 0:
            msg = err.strip() or f"scp exited with code {rc}"
            failed[router.name] = msg
            print(f"  FAIL: {msg}")
        else:
            copied[router.name] = image_path
            print("  OK copied")

        print()

    return copied, failed


def build_async_upgrade_command(remote_image_path: str) -> str:
    payload = (
        f"sleep {ASYNC_SYSUPGRADE_DELAY_SEC}; "
        f"sysupgrade -n {shlex.quote(remote_image_path)}"
    )

    return f"setsid sh -c {shlex.quote(payload)} " "</dev/null >/dev/null 2>&1 &"


def filter_routers_by_names(
    routers: list[RouterDef],
    names: list[str],
) -> list[RouterDef]:
    if not names:
        return routers

    known = {router.name.lower() for router in routers}

    for name in names:
        if name.lower() not in known:
            die(f"unknown router: {name}")

    wanted = {name.lower() for name in names}
    return [router for router in routers if router.name.lower() in wanted]


def start_upgrades(
    routers: list[RouterDef],
    copied: dict[str, Path],
    remote_dir: str,
    ssh_timeout: int,
    config_path: str | Path = CONFIG_PATH,
) -> dict[str, str]:
    failed: dict[str, str] = {}

    for router in routers:
        image_path = copied.get(router.name)
        if image_path is None:
            continue

        remote_image = f"{remote_dir.rstrip('/')}/{image_path.name}"
        remote_cmd = build_async_upgrade_command(remote_image)

        print(f"{router.name} ({router.ssh_host})")
        print(f"  start: {remote_image}")

        rc, _out, err = run_ssh(
            host=router.ssh_host,
            command=remote_cmd,
            ssh_timeout=ssh_timeout,
            config_path=config_path,
        )

        if rc != 0:
            msg = err.strip() or f"ssh exited with code {rc}"
            failed[router.name] = msg
            print(f"  FAIL: {msg}")
        else:
            print("  OK started asynchronously")

        print()

    return failed


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Copy firmware images from images/ to routers in order: "
            "all leafs, then mesh_hubs except main_router, then main_router; "
            "after confirmation start async sysupgrade"
        )
    )
    ap.add_argument(
        "git_version",
        help="git version to match in image names, for example e47e68e",
    )
    ap.add_argument(
        "routers",
        nargs="*",
        help=(
            "router names, for example: Spine01 Leaf01 or Spine01,Leaf01. "
            "If omitted or set to 'all', pushes to all routers"
        ),
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to config.json (default: config.json)",
    )
    ap.add_argument(
        "--result-dir",
        default=str(RESULT_DIR),
        help="directory with build artifacts (default: images)",
    )
    ap.add_argument(
        "--remote-dir",
        default=REMOTE_UPLOAD_DIR,
        help=f"remote directory for upload (default: {REMOTE_UPLOAD_DIR})",
    )
    ap.add_argument(
        "--ssh-timeout",
        type=int,
        default=SSH_TIMEOUT,
        help=f"ssh connect timeout in seconds (default: {SSH_TIMEOUT})",
    )
    ap.add_argument(
        "--scp-timeout",
        type=int,
        default=SCP_TIMEOUT,
        help=f"scp connect timeout in seconds (default: {SCP_TIMEOUT})",
    )
    ap.add_argument(
        "--no-clear",
        action="store_true",
        help="do not clear screen before output",
    )
    args = ap.parse_args()

    cfg = load_json_config(Path(args.config))
    routers = build_router_order(cfg)
    router_names = parse_csv_names(args.routers)
    routers = filter_routers_by_names(routers, router_names)

    if not routers:
        die("no routers defined in config")

    result_dir = Path(args.result_dir)
    if not result_dir.exists() or not result_dir.is_dir():
        die(f"images directory does not exist or is not a directory: {result_dir}")

    clear_screen(not args.no_clear)

    print("=== COPYING IMAGES ===")
    print()

    copied, copy_failed = copy_images(
        routers=routers,
        git_version=args.git_version,
        result_dir=result_dir,
        remote_dir=args.remote_dir,
        scp_timeout=args.scp_timeout,
        config_path=args.config,
    )

    print("=== COPY SUMMARY ===")
    print(f"copied: {len(copied)}")
    print(f"failed: {len(copy_failed)}")
    print()

    if copy_failed:
        print("copy failed on:")
        for router_name, reason in copy_failed.items():
            print(f"  {router_name}: {reason}")
        print()
    else:
        print("all images copied successfully")
        print()

    if not copied:
        die("nothing was copied successfully, aborting")

    proceed = ask_yes_no("continue with async sysupgrade? yes/no: ")
    if not proceed:
        print("aborted by user")
        sys.exit(1)

    print()
    print("=== STARTING ASYNC UPGRADES ===")
    print()

    start_failed = start_upgrades(
        routers=routers,
        copied=copied,
        remote_dir=args.remote_dir,
        ssh_timeout=args.ssh_timeout,
        config_path=args.config,
    )

    print("=== START SUMMARY ===")
    print(f"started: {len(copied) - len(start_failed)}")
    print(f"failed to start: {len(start_failed)}")
    print()

    if start_failed:
        print("failed to start on:")
        for router_name, reason in start_failed.items():
            print(f"  {router_name}: {reason}")
        sys.exit(1)

    print("async sysupgrade started on all copied routers")
    sys.exit(0)


if __name__ == "__main__":
    main()
