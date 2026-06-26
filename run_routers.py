#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

from tools.cli_common import clear_screen, command_from_argv
from tools.config_io import load_json_config
from tools.process import die
from tools.remote_exec import run_and_print_captured_remote
from tools.default import CONFIG_PATH, SSH_TIMEOUT, ROUTER_VERSION_COMMAND
from tools.router_order import RouterDef, build_router_order


def run_on_router(
    router: RouterDef,
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> bool:
    return run_and_print_captured_remote(
        router.ssh_host,
        (router.ssh_host,),
        command,
        ssh_timeout=ssh_timeout,
        config_path=config_path,
    )


def run_on_all_routers(
    routers: list[RouterDef],
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> int:
    had_error = False

    for router in routers:
        if not run_on_router(
            router, command, ssh_timeout=ssh_timeout, config_path=config_path
        ):
            had_error = True

    return 1 if had_error else 0


def show_router_versions(
    routers: list[RouterDef],
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> int:
    return run_on_all_routers(
        routers,
        ROUTER_VERSION_COMMAND,
        ssh_timeout=ssh_timeout,
        config_path=config_path,
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Run command on routers in order: "
            "all non-mesh routers, then mesh_hubs except main_router, then main_router"
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to config.json (default: config.json)",
    )
    ap.add_argument(
        "--ssh-timeout",
        type=int,
        default=SSH_TIMEOUT,
        help=f"SSH connect timeout in seconds (default: {SSH_TIMEOUT})",
    )
    ap.add_argument(
        "--no-clear",
        action="store_true",
        help="do not clear screen before output",
    )
    ap.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="remote command to run; if omitted, show OpenWrt versions",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    cfg = load_json_config(Path(args.config))
    routers = build_router_order(cfg)

    if not routers:
        die("no routers defined in config")

    clear_screen(not args.no_clear)

    if args.command:
        rc = run_on_all_routers(
            routers=routers,
            command=command_from_argv(args.command),
            ssh_timeout=args.ssh_timeout,
            config_path=args.config,
        )
    else:
        rc = show_router_versions(
            routers=routers,
            ssh_timeout=args.ssh_timeout,
            config_path=args.config,
        )

    sys.exit(rc)


if __name__ == "__main__":
    main()
