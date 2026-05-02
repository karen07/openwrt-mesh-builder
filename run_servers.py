#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

from tools.cli_common import clear_screen, command_from_argv
from tools.config_io import load_json_config
from tools.process import die
from tools.remote_hosts import server_ssh_hosts
from tools.remote_exec import run_and_print_captured_remote
from tools.targets import selected_servers
from tools.default import (
    CONFIG_PATH,
    SSH_TIMEOUT,
    SERVER_VERSION_COMMAND,
)


def run_on_server(
    name: str,
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
    server_ssh_mode: str = "auto",
) -> bool:
    hosts = server_ssh_hosts(name, server_ssh_mode)
    return run_and_print_captured_remote(
        "/".join(hosts),
        hosts,
        command,
        ssh_timeout=ssh_timeout,
        config_path=config_path,
    )


def run_on_all_servers(
    servers: list[str],
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
    server_ssh_mode: str = "auto",
) -> int:
    had_error = False

    for name in servers:
        if not run_on_server(
            name,
            command,
            ssh_timeout=ssh_timeout,
            config_path=config_path,
            server_ssh_mode=server_ssh_mode,
        ):
            had_error = True

    return 1 if had_error else 0


def show_server_versions(
    servers: list[str],
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
    server_ssh_mode: str = "auto",
) -> int:
    return run_on_all_servers(
        servers,
        SERVER_VERSION_COMMAND,
        ssh_timeout=ssh_timeout,
        config_path=config_path,
        server_ssh_mode=server_ssh_mode,
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Run command on generated servers. "
            "If command is omitted, show server deploy versions."
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
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
        "--servers",
        default="",
        help=(
            "server names to run on, comma- or space-separated; "
            "quote spaces, for example --servers 'EGR01 REV01'; default: all"
        ),
    )
    ap.add_argument(
        "--server-ssh-mode",
        choices=("auto", "node", "public"),
        default="auto",
        help=(
            "server SSH alias mode: auto tries server_<name>_node first "
            "then server_<name>; node/public force one alias"
        ),
    )
    ap.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="remote command to run; if omitted, show server deploy versions",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_json_config(Path(args.config))
    servers = selected_servers(cfg, [args.servers] if args.servers else [])

    if not servers:
        die("no exit_hubs defined in config")

    clear_screen(not args.no_clear)

    if args.command:
        rc = run_on_all_servers(
            servers=servers,
            command=command_from_argv(args.command),
            ssh_timeout=args.ssh_timeout,
            config_path=args.config,
            server_ssh_mode=args.server_ssh_mode,
        )
    else:
        rc = show_server_versions(
            servers=servers,
            ssh_timeout=args.ssh_timeout,
            config_path=args.config,
            server_ssh_mode=args.server_ssh_mode,
        )

    sys.exit(rc)


if __name__ == "__main__":
    main()
