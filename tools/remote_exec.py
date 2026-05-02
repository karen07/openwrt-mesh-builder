#!/usr/bin/env python3
"""Remote ssh/scp execution helpers.

This module is the Unix-tool boundary for remote operations.  Higher-level
scripts describe targets and actions; this module decides how to run ssh/scp,
how fallback hosts are tried, and how captured output is reported.
"""

import sys

sys.dont_write_bytecode = True
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from .config_io import load_json_config
    from .process import die, run_command, run_interactive
    from .default import (
        CONFIG_PATH,
        CONFIG_KEY_SSH_KEY_DIR,
        SCP_COMMAND_TIMEOUT_GRACE_SEC,
        SCP_TIMEOUT,
        SSH_COMMAND_TIMEOUT_GRACE_SEC,
        SSH_CONFIG_FILENAME,
        SSH_TIMEOUT,
    )
except ImportError:
    from config_io import load_json_config  # type: ignore
    from process import die, run_command, run_interactive  # type: ignore
    from default import (  # type: ignore
        CONFIG_PATH,
        CONFIG_KEY_SSH_KEY_DIR,
        SCP_COMMAND_TIMEOUT_GRACE_SEC,
        SCP_TIMEOUT,
        SSH_COMMAND_TIMEOUT_GRACE_SEC,
        SSH_CONFIG_FILENAME,
        SSH_TIMEOUT,
    )


def expand_user_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def deploy_ssh_dir_from_config(cfg: dict[str, object]) -> Path:
    raw_dir = cfg.get(CONFIG_KEY_SSH_KEY_DIR)
    if raw_dir is None:
        die(
            f"missing required config key {CONFIG_KEY_SSH_KEY_DIR!r}; "
            "set it explicitly, for example: "
            '"ssh_key_dir": "~/.ssh/router-autoinstall-prod"'
        )
    if not isinstance(raw_dir, str) or not raw_dir.strip():
        die(f"config key {CONFIG_KEY_SSH_KEY_DIR!r} must be a non-empty string")
    return expand_user_path(raw_dir)


def deploy_ssh_config_path_from_config(cfg: dict[str, object]) -> Path:
    return deploy_ssh_dir_from_config(cfg) / SSH_CONFIG_FILENAME


def current_deploy_ssh_config_path(
    config_path: str | Path = CONFIG_PATH,
) -> Path | None:
    """Return this deployment's generated SSH config, if it exists."""
    path = Path(config_path)
    if not path.exists():
        return None

    cfg = load_json_config(path)
    ssh_config = deploy_ssh_config_path_from_config(cfg)
    if ssh_config.exists():
        return ssh_config
    return None


def ssh_config_args(config_path: str | Path = CONFIG_PATH) -> list[str]:
    path = current_deploy_ssh_config_path(config_path)
    if path is None:
        return []
    return ["-F", str(path)]


def run_ssh(
    host: str,
    command: str,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[int, str, str]:
    return run_command(
        [
            "ssh",
            *ssh_config_args(config_path),
            "-o",
            f"ConnectTimeout={ssh_timeout}",
            "-o",
            "BatchMode=yes",
            host,
            command,
        ],
        timeout=ssh_timeout + SSH_COMMAND_TIMEOUT_GRACE_SEC,
    )


def scp_to_host(
    *,
    local_path: Path,
    remote_host: str,
    remote_dir: str,
    scp_timeout: int = SCP_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> tuple[int, str, str]:
    remote_target = f"{remote_host}:{remote_dir.rstrip('/')}/"
    return run_command(
        [
            "scp",
            *ssh_config_args(config_path),
            "-O",
            "-o",
            f"ConnectTimeout={scp_timeout}",
            "-o",
            "BatchMode=yes",
            str(local_path),
            remote_target,
        ],
        timeout=scp_timeout + SCP_COMMAND_TIMEOUT_GRACE_SEC,
    )


@dataclass(frozen=True)
class CapturedRemoteResult:
    label: str
    hosts: tuple[str, ...]
    host: str
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def fallback_used(self) -> bool:
        return len(self.hosts) > 1 and self.host != self.hosts[0]

    def error_text(self) -> str:
        return self.err.strip() or f"ssh exited with code {self.rc}"


@dataclass(frozen=True)
class CapturedTransferResult:
    label: str
    host: str
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def error_text(self) -> str:
        return self.err.strip() or f"scp exited with code {self.rc}"


def run_captured_remote(
    label: str,
    hosts: tuple[str, ...] | list[str],
    command: str,
    *,
    ssh_timeout: int = SSH_TIMEOUT,
    command_timeout: int | None = None,
    config_path: str | Path = CONFIG_PATH,
) -> CapturedRemoteResult:
    host_tuple = tuple(hosts)
    if not host_tuple:
        raise ValueError(f"{label}: empty SSH host list")

    timeout = command_timeout if command_timeout is not None else ssh_timeout
    last_host = host_tuple[-1]
    last_rc = 1
    last_out = ""
    last_err = "no SSH hosts tried"

    for host in host_tuple:
        rc, out, err = run_ssh(
            host,
            command,
            ssh_timeout=timeout,
            config_path=config_path,
        )
        if rc == 0:
            return CapturedRemoteResult(label, host_tuple, host, rc, out, err)
        last_host, last_rc, last_out, last_err = host, rc, out, err

    return CapturedRemoteResult(
        label,
        host_tuple,
        last_host,
        last_rc,
        last_out,
        last_err,
    )


def print_captured_remote_result(result: CapturedRemoteResult) -> bool:
    print(f"{result.label}:")
    if result.fallback_used:
        print(f"using fallback SSH host: {result.host}")

    if result.out:
        print(result.out.rstrip())

    if not result.ok:
        print(result.error_text(), file=sys.stderr)

    print()
    return result.ok


def run_and_print_captured_remote(
    label: str,
    hosts: tuple[str, ...] | list[str],
    command: str,
    *,
    ssh_timeout: int = SSH_TIMEOUT,
    config_path: str | Path = CONFIG_PATH,
) -> bool:
    return print_captured_remote_result(
        run_captured_remote(
            label,
            hosts,
            command,
            ssh_timeout=ssh_timeout,
            config_path=config_path,
        )
    )


def interactive_ssh_timeout_args(connect_timeout: int) -> list[str]:
    return [
        "-o",
        f"ConnectTimeout={connect_timeout}",
        "-o",
        "ConnectionAttempts=1",
    ]


def run_interactive_ssh(
    host: str,
    command: str,
    *,
    config_path: str | Path = CONFIG_PATH,
    connect_timeout: int,
    input_data: bytes | None = None,
) -> int:
    return run_interactive(
        [
            "ssh",
            *ssh_config_args(config_path),
            *interactive_ssh_timeout_args(connect_timeout),
            host,
            command,
        ],
        input_data=input_data,
    )


def scp_paths_interactive(
    paths: list[Path],
    host: str,
    remote_dir: str,
    *,
    config_path: str | Path = CONFIG_PATH,
    connect_timeout: int,
) -> int:
    return run_interactive(
        [
            "scp",
            *ssh_config_args(config_path),
            *interactive_ssh_timeout_args(connect_timeout),
            "-rp",
            *(str(path) for path in paths),
            f"{host}:{remote_dir.rstrip('/')}/",
        ]
    )


def scp_path_captured(
    label: str,
    local_path: Path,
    host: str,
    remote_dir: str,
    *,
    scp_timeout: int,
    config_path: str | Path = CONFIG_PATH,
) -> CapturedTransferResult:
    rc, out, err = scp_to_host(
        local_path=local_path,
        remote_host=host,
        remote_dir=remote_dir,
        scp_timeout=scp_timeout,
        config_path=config_path,
    )
    return CapturedTransferResult(label, host, rc, out, err)
