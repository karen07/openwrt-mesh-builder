#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from tools.config_io import load_json_config
    from tools.process import die, need
    from tools.common import server_exit_dir
    from tools.remote_exec import (
        run_interactive_ssh,
        scp_paths_interactive,
    )
    from tools.remote_hosts import SERVER_SSH_MODE_CHOICES, server_ssh_hosts
    from tools.default import CONFIG_PATH, REMOTE_DEPLOY_COMMAND, REMOTE_ROOT
    from tools.git_utils import git_short
    from tools.secrets import assert_no_markers, decrypt_tree
    from tools.targets import selected_servers
except ImportError:
    from config_io import load_json_config
    from process import die, need
    from common import server_exit_dir
    from remote_exec import (
        run_interactive_ssh,
        scp_paths_interactive,
    )
    from remote_hosts import SERVER_SSH_MODE_CHOICES, server_ssh_hosts
    from default import CONFIG_PATH, REMOTE_DEPLOY_COMMAND, REMOTE_ROOT
    from git_utils import git_short
    from secrets import assert_no_markers, decrypt_tree
    from targets import selected_servers


class DeployError(Exception):
    pass


DEFAULT_SSH_CONNECT_TIMEOUT_SEC = 5


def server_deploy_version() -> str:
    deploy_time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    return f"{git_short()} {deploy_time}\n"


def project_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_config_path(config_path: str) -> Path:
    path = Path(config_path)
    if path.is_absolute():
        return path
    return project_root() / path


def copy_server_tree(src: Path, dst: Path) -> None:
    entries = [
        path
        for path in sorted(src.iterdir(), key=lambda p: p.name)
        if not path.name.startswith(".")
    ]

    if not entries:
        die(f"no files to copy in server directory: {src}")

    for path in entries:
        target = dst / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.is_file():
            shutil.copy2(path, target)
        else:
            die(f"unsupported server tree entry: {path}")


def extract_server_authorized_keys(stage: Path) -> bytes | None:
    """Read and remove staged root/.ssh/authorized_keys before scp.

    The staged key file is installed over ssh before the rest of the tree is
    copied. This makes the generated key available for the following scp and
    ssh calls, while also avoiding an scp overwrite of remote authorized_keys.
    """
    auth_file = stage / "root" / ".ssh" / "authorized_keys"

    if not auth_file.exists():
        return None
    if not auth_file.is_file():
        die(f"unsupported server authorized_keys entry: {auth_file}")

    data = auth_file.read_bytes()
    auth_file.unlink()
    return data


def stage_server_files(name: str, src: Path, tmp_root: Path, config_path: Path) -> Path:
    stage = tmp_root / name
    stage.mkdir(parents=True)

    copy_server_tree(src, stage)

    root_dir = stage / "root"
    root_dir.mkdir(exist_ok=True)
    (root_dir / "deploy_version").write_text(
        server_deploy_version(),
        encoding="utf-8",
    )

    decrypt_tree([stage], config_path=config_path)
    assert_no_markers([stage])

    return stage


def copy_server_files(
    name: str,
    host: str,
    src: Path,
    config_path: Path,
    *,
    connect_timeout: int,
) -> None:
    entries = sorted(src.iterdir(), key=lambda p: p.name)

    if not entries:
        die(f"no staged files to copy in server directory: {src}")

    # Intentionally do not capture stdio:
    # scp must be able to ask for password / host-key confirmation.
    rc = scp_paths_interactive(
        entries,
        host,
        REMOTE_ROOT,
        config_path=config_path,
        connect_timeout=connect_timeout,
    )

    if rc != 0:
        raise DeployError(f"scp failed for {name} via {host} with exit code {rc}")


def install_server_authorized_keys(
    name: str,
    host: str,
    auth_data: bytes | None,
    *,
    replace: bool,
    config_path: Path,
    connect_timeout: int,
) -> None:
    if auth_data is None:
        return

    if replace:
        remote_cmd = (
            "mkdir -p /root/.ssh && "
            "chmod 0700 /root/.ssh && "
            "cat > /root/.ssh/authorized_keys && "
            "chmod 0600 /root/.ssh/authorized_keys"
        )
        action = "replace"
    else:
        remote_cmd = (
            "set -eu; "
            "tmp=$(mktemp); "
            "merged=$(mktemp); "
            'trap \'rm -f "$tmp" "$merged"\' EXIT; '
            'cat > "$tmp"; '
            "mkdir -p /root/.ssh; "
            "chmod 0700 /root/.ssh; "
            "touch /root/.ssh/authorized_keys; "
            "chmod 0600 /root/.ssh/authorized_keys; "
            'cat /root/.ssh/authorized_keys "$tmp" | '
            "awk 'NF && !seen[$0]++' > \"$merged\"; "
            'cat "$merged" > /root/.ssh/authorized_keys; '
            "chmod 0600 /root/.ssh/authorized_keys"
        )
        action = "merge"

    rc = run_interactive_ssh(
        host,
        remote_cmd,
        config_path=config_path,
        connect_timeout=connect_timeout,
        input_data=auth_data,
    )

    if rc != 0:
        raise DeployError(
            f"authorized_keys {action} failed for {name} via {host} with exit code {rc}"
        )


def run_remote_deploy(
    name: str,
    host: str,
    config_path: Path,
    *,
    connect_timeout: int,
) -> None:
    # Intentionally do not capture stdio:
    # ssh must be able to ask for password / host-key confirmation.
    rc = run_interactive_ssh(
        host,
        REMOTE_DEPLOY_COMMAND,
        config_path=config_path,
        connect_timeout=connect_timeout,
    )

    if rc != 0:
        raise DeployError(
            f"remote deploy failed for {name} via {host} with exit code {rc}"
        )


def deploy_one_to_host(
    name: str,
    host: str,
    *,
    replace_authorized_keys: bool,
    config_path: Path,
    connect_timeout: int,
) -> None:
    src = server_exit_dir(name)

    print()
    print(f"==> Preparing {name} for {host}")

    with tempfile.TemporaryDirectory(
        prefix=f".server-deploy-{name}-",
        dir=Path.cwd(),
    ) as tmp:
        tmp_root = Path(tmp)
        stage = stage_server_files(name, src, tmp_root, config_path)
        auth_data = extract_server_authorized_keys(stage)

        if auth_data is not None:
            action = "Replacing" if replace_authorized_keys else "Appending"
            print(f"==> {action} authorized_keys for {name} on {host}")
        install_server_authorized_keys(
            name,
            host,
            auth_data,
            replace=replace_authorized_keys,
            config_path=config_path,
            connect_timeout=connect_timeout,
        )

        print(f"==> Copying files for {name} to {host}:{REMOTE_ROOT}")

        copy_server_files(
            name,
            host,
            stage,
            config_path,
            connect_timeout=connect_timeout,
        )

        print(f"==> Running remote deploy.sh on {host}")

        run_remote_deploy(
            name,
            host,
            config_path,
            connect_timeout=connect_timeout,
        )


def deploy_one(
    name: str,
    *,
    replace_authorized_keys: bool,
    config_path: Path,
    server_ssh_mode: str,
    connect_timeout: int,
) -> None:
    src = server_exit_dir(name)

    if not src.is_dir():
        die(f"missing server directory: {src}")

    errors: list[str] = []
    hosts = server_ssh_hosts(name, server_ssh_mode)

    for idx, host in enumerate(hosts):
        if idx > 0:
            print(f"==> Trying fallback SSH host for {name}: {host}")
        try:
            deploy_one_to_host(
                name,
                host,
                replace_authorized_keys=replace_authorized_keys,
                config_path=config_path,
                connect_timeout=connect_timeout,
            )
            print(f"==> OK: {name} deployed via {host}")
            return
        except DeployError as e:
            errors.append(str(e))
            print(f"WARNING: {e}", file=sys.stderr)

    die(f"all SSH hosts failed for {name}: " + "; ".join(errors))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy generated exit-server files over scp/ssh.",
    )
    parser.add_argument(
        "servers",
        nargs="*",
        help="server names to deploy; defaults to all generated servers",
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    parser.add_argument(
        "--replace-authorized-keys",
        action="store_true",
        help=(
            "replace remote /root/.ssh/authorized_keys with the staged file; "
            "by default staged keys are merged without duplicates"
        ),
    )
    parser.add_argument(
        "--server-ssh-mode",
        choices=SERVER_SSH_MODE_CHOICES,
        default="auto",
        help=(
            "server SSH alias mode: auto tries server_<name>_node first "
            "then server_<name>; node/public force one alias"
        ),
    )
    parser.add_argument(
        "--ssh-connect-timeout",
        type=int,
        default=DEFAULT_SSH_CONNECT_TIMEOUT_SEC,
        metavar="SECONDS",
        help=(
            "ConnectTimeout passed to interactive ssh/scp calls; "
            f"default: {DEFAULT_SSH_CONNECT_TIMEOUT_SEC}"
        ),
    )
    args = parser.parse_args(argv)
    if args.ssh_connect_timeout < 1:
        die("--ssh-connect-timeout must be a positive integer")
    return args


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    need("scp", "ssh")
    config_path = resolve_config_path(args.config)
    cfg = load_json_config(config_path)

    servers = selected_servers(cfg, args.servers)
    if not servers:
        die("no servers selected")

    print("Selected servers:")
    for name in servers:
        print(f"  {name}")

    if args.replace_authorized_keys:
        print("authorized_keys mode: replace")
    else:
        print("authorized_keys mode: append")

    for name in servers:
        deploy_one(
            name,
            replace_authorized_keys=args.replace_authorized_keys,
            config_path=config_path,
            server_ssh_mode=args.server_ssh_mode,
            connect_timeout=args.ssh_connect_timeout,
        )


if __name__ == "__main__":
    main(sys.argv[1:])
