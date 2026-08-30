#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import shlex
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

AWG_SERVER_NETWORK_SERVICE = "awg-server-network.service"
EXIT_DIRECT_GUARD_SERVICE = "exit-direct-guard.service"
EXIT_DIRECT_GUARD_TIMER = "exit-direct-guard.timer"
REMOTE_AUTHORIZED_KEYS = "/root/.ssh/authorized_keys"
REMOTE_AMNEZIAWG_DIR = "/etc/amnezia/amneziawg"
REMOTE_SYSTEMD_DIR = "/etc/systemd/system"


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
        raise DeployError(f"no files to copy in server directory: {src}")

    for path in entries:
        target = dst / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        elif path.is_file():
            shutil.copy2(path, target)
        else:
            raise DeployError(f"unsupported server tree entry: {path}")


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
        raise DeployError(f"unsupported server authorized_keys entry: {auth_file}")

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
        raise DeployError(f"no staged files to copy in server directory: {src}")

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


def read_server_authorized_keys(src: Path) -> bytes:
    auth_file = src / "root" / ".ssh" / "authorized_keys"
    if not auth_file.exists():
        raise DeployError(f"missing server authorized_keys: {auth_file}")
    if not auth_file.is_file():
        raise DeployError(f"unsupported server authorized_keys entry: {auth_file}")

    data = auth_file.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DeployError(f"server authorized_keys is not UTF-8: {auth_file}") from e

    if not any(line.strip() for line in text.splitlines()):
        raise DeployError(f"server authorized_keys is empty: {auth_file}")
    return data


def server_undeploy_remote_files(src: Path) -> list[str]:
    """Return exact remote files copied from the generated server tree.

    Shared parent directories are deliberately not returned.  The AWG config
    directory is owned as a whole by this project and is removed separately.
    authorized_keys is also handled separately so unrelated SSH keys survive.
    """
    auth_rel = Path("root/.ssh/authorized_keys")
    awg_rel = Path("etc/amnezia/amneziawg")
    systemd_rel = Path("etc/systemd/system")
    unit_names = {
        AWG_SERVER_NETWORK_SERVICE,
        EXIT_DIRECT_GUARD_SERVICE,
        EXIT_DIRECT_GUARD_TIMER,
    }

    paths: set[str] = set()
    for path in src.rglob("*"):
        if not path.is_file():
            continue

        rel = path.relative_to(src)
        if rel.parts and rel.parts[0].startswith("."):
            # copy_server_tree() never deploys hidden top-level entries.
            continue
        if rel == auth_rel:
            continue
        if rel == awg_rel or awg_rel in rel.parents:
            continue
        if rel.parent == systemd_rel and rel.name in unit_names:
            continue

        paths.add("/" + rel.as_posix())

    # deploy.sh consumes /root/deploy_version into /etc/deploy_version.  Keep
    # both cleanup paths so undeploy is safe after either a completed or an
    # interrupted deployment.
    paths.add("/etc/deploy_version")
    paths.add("/root/deploy_version")
    return sorted(paths)


def build_undeploy_script(src: Path, auth_data: bytes) -> bytes:
    try:
        auth_text = auth_data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DeployError("server authorized_keys is not UTF-8") from e

    auth_lines = [line for line in auth_text.splitlines() if line.strip()]
    if not auth_lines:
        raise DeployError("server authorized_keys has no non-empty keys")

    delimiter = "OWMB_UNDEPLOY_AUTHORIZED_KEYS"
    while delimiter in auth_lines:
        delimiter += "_X"

    systemd_units = [
        f"{REMOTE_SYSTEMD_DIR}/{AWG_SERVER_NETWORK_SERVICE}",
        f"{REMOTE_SYSTEMD_DIR}/{EXIT_DIRECT_GUARD_SERVICE}",
        f"{REMOTE_SYSTEMD_DIR}/{EXIT_DIRECT_GUARD_TIMER}",
    ]
    managed_files = server_undeploy_remote_files(src)

    lines = [
        "#!/bin/sh",
        "set -eu",
        "",
        f"systemctl disable {shlex.quote(AWG_SERVER_NETWORK_SERVICE)} >/dev/null 2>&1 || true",
        f"systemctl disable {shlex.quote(EXIT_DIRECT_GUARD_TIMER)} >/dev/null 2>&1 || true",
        f"systemctl stop {shlex.quote(EXIT_DIRECT_GUARD_TIMER)} >/dev/null 2>&1 || true",
        "",
        "rm -f " + " ".join(shlex.quote(path) for path in systemd_units),
        "systemctl daemon-reload",
        "",
        f"rm -rf {shlex.quote(REMOTE_AMNEZIAWG_DIR)}",
    ]

    if managed_files:
        lines.append("rm -f " + " ".join(shlex.quote(path) for path in managed_files))

    lines.extend(
        [
            "",
            "keys_tmp=$(mktemp)",
            "filtered_tmp=$(mktemp)",
            'trap \'rm -f "$keys_tmp" "$filtered_tmp"\' EXIT',
            f"cat > \"$keys_tmp\" <<'{delimiter}'",
            *auth_lines,
            delimiter,
            f"if [ -f {shlex.quote(REMOTE_AUTHORIZED_KEYS)} ]; then",
            (
                "    awk 'NR==FNR { if (NF) remove[$0]=1; next } "
                f'!($0 in remove)\' "$keys_tmp" {shlex.quote(REMOTE_AUTHORIZED_KEYS)} '
                '> "$filtered_tmp"'
            ),
            f'    cat "$filtered_tmp" > {shlex.quote(REMOTE_AUTHORIZED_KEYS)}',
            f"    chmod 0600 {shlex.quote(REMOTE_AUTHORIZED_KEYS)}",
            "fi",
            'rm -f "$keys_tmp" "$filtered_tmp"',
            "trap - EXIT",
            "",
            "systemctl reboot --no-block",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def run_remote_undeploy(
    name: str,
    host: str,
    src: Path,
    auth_data: bytes,
    config_path: Path,
    *,
    connect_timeout: int,
) -> None:
    rc = run_interactive_ssh(
        host,
        "sh -s",
        config_path=config_path,
        connect_timeout=connect_timeout,
        input_data=build_undeploy_script(src, auth_data),
    )

    if rc != 0:
        raise DeployError(
            f"remote undeploy failed for {name} via {host} with exit code {rc}"
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


def undeploy_one_to_host(
    name: str,
    host: str,
    *,
    src: Path,
    auth_data: bytes,
    config_path: Path,
    connect_timeout: int,
) -> None:
    print()
    print(f"==> Undeploying {name} from {host}")
    run_remote_undeploy(
        name,
        host,
        src,
        auth_data,
        config_path,
        connect_timeout=connect_timeout,
    )


def undeploy_one(
    name: str,
    *,
    config_path: Path,
    server_ssh_mode: str,
    connect_timeout: int,
) -> str:
    src = server_exit_dir(name)

    if not src.is_dir():
        raise DeployError(f"missing server directory: {src}")

    auth_data = read_server_authorized_keys(src)
    errors: list[str] = []
    hosts = server_ssh_hosts(name, server_ssh_mode)

    for idx, host in enumerate(hosts):
        if idx > 0:
            print(f"==> Trying fallback SSH host for {name}: {host}")
        try:
            undeploy_one_to_host(
                name,
                host,
                src=src,
                auth_data=auth_data,
                config_path=config_path,
                connect_timeout=connect_timeout,
            )
            print(f"==> OK: {name} undeployed via {host}; reboot requested")
            return host
        except DeployError as e:
            errors.append(str(e))
            print(f"WARNING: {e}", file=sys.stderr)

    raise DeployError(f"all SSH hosts failed for {name}: " + "; ".join(errors))


def deploy_one(
    name: str,
    *,
    replace_authorized_keys: bool,
    config_path: Path,
    server_ssh_mode: str,
    connect_timeout: int,
) -> str:
    src = server_exit_dir(name)

    if not src.is_dir():
        raise DeployError(f"missing server directory: {src}")

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
            return host
        except DeployError as e:
            errors.append(str(e))
            print(f"WARNING: {e}", file=sys.stderr)

    raise DeployError(f"all SSH hosts failed for {name}: " + "; ".join(errors))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy or undeploy generated exit-server files over scp/ssh.",
    )
    parser.add_argument(
        "servers",
        nargs="*",
        help="server names to deploy/undeploy; defaults to all generated servers",
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    parser.add_argument(
        "--undeploy",
        action="store_true",
        help=(
            "remove this project's deployed server files and SSH key, then reboot; "
            "AWG network state is left running until reboot"
        ),
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
    if args.undeploy and args.replace_authorized_keys:
        die("--replace-authorized-keys cannot be used with --undeploy")
    return args


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    if args.undeploy:
        need("ssh")
    else:
        need("scp", "ssh")
    config_path = resolve_config_path(args.config)
    cfg = load_json_config(config_path)

    servers = selected_servers(cfg, args.servers)
    if not servers:
        die("no servers selected")

    print("Selected servers:")
    for name in servers:
        print(f"  {name}")

    if args.undeploy:
        print("Mode: undeploy")
    elif args.replace_authorized_keys:
        print("authorized_keys mode: replace")
    else:
        print("authorized_keys mode: append")

    completed: dict[str, str] = {}
    failed: dict[str, str] = {}
    operation = "undeploy" if args.undeploy else "deploy"

    for name in servers:
        try:
            if args.undeploy:
                host = undeploy_one(
                    name,
                    config_path=config_path,
                    server_ssh_mode=args.server_ssh_mode,
                    connect_timeout=args.ssh_connect_timeout,
                )
            else:
                host = deploy_one(
                    name,
                    replace_authorized_keys=args.replace_authorized_keys,
                    config_path=config_path,
                    server_ssh_mode=args.server_ssh_mode,
                    connect_timeout=args.ssh_connect_timeout,
                )
            completed[name] = host
        except DeployError as e:
            reason = str(e)
            failed[name] = reason
            print(f"==> FAIL: {name}: {reason}", file=sys.stderr)
        except SystemExit as e:
            # Helpers used while preparing one server may call die().  Once the
            # operation loop has started, treat that as a failure of this
            # server and continue with the remaining servers.
            code = e.code if isinstance(e.code, int) else 1
            reason = f"{operation} aborted with exit code {code}"
            failed[name] = reason
            print(f"==> FAIL: {name}: {reason}", file=sys.stderr)
        except Exception as e:
            reason = f"unexpected error: {e}"
            failed[name] = reason
            print(f"==> FAIL: {name}: {reason}", file=sys.stderr)

    print()
    print(f"=== {operation.upper()} SUMMARY ===")
    print(f"{operation}ed: {len(completed)}")
    print(f"failed: {len(failed)}")
    print()

    if failed:
        print("failed on:")
        for name, reason in failed.items():
            print(f"  {name}: {reason}")
        sys.exit(1)

    print(f"all servers {operation}ed successfully")
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
