#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import subprocess
from pathlib import Path

try:
    from .cli_common import (
        atomic_write_text,
        deploy_ssh_config_path_from_config,
        deploy_ssh_dir_from_config,
        load_json_config,
        need,
        run_checked,
    )
except ImportError:
    from cli_common import (
        atomic_write_text,
        deploy_ssh_config_path_from_config,
        deploy_ssh_dir_from_config,
        load_json_config,
        need,
        run_checked,
    )

try:
    from .default import (
        CONFIG_PATH,
        PRIVATE_KEY_FILE_MODE,
        PRIVATE_SSH_DIR_MODE,
        REL_DROPBEAR_AUTHORIZED_KEYS,
        ROUTERS_ROOT,
        ROUTER_KEY_PREFIX as ROUTER_PREFIX,
        SERVER_KEY_PREFIX as SERVER_PREFIX,
        SSH_KNOWN_HOSTS_FILENAME,
    )
except ImportError:
    from default import (
        CONFIG_PATH,
        PRIVATE_KEY_FILE_MODE,
        PRIVATE_SSH_DIR_MODE,
        REL_DROPBEAR_AUTHORIZED_KEYS,
        ROUTERS_ROOT,
        ROUTER_KEY_PREFIX as ROUTER_PREFIX,
        SERVER_KEY_PREFIX as SERVER_PREFIX,
        SSH_KNOWN_HOSTS_FILENAME,
    )

try:
    from .common import ConfigData, ExitHub, build_config_data, server_exit_dir
except ImportError:
    from common import ConfigData, ExitHub, build_config_data, server_exit_dir


def ensure_dir(path: Path, mode: int | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        path.chmod(mode)


def server_key_name(exit_name: str) -> str:
    return f"{SERVER_PREFIX}{exit_name.lower()}"


def ensure_key_and_write_pub(key_base: Path, auth_file: Path, comment: str) -> None:
    priv_key = key_base

    if not priv_key.exists():
        print(f"Generating key: {priv_key}")
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(priv_key),
                "-N",
                "",
                "-C",
                comment,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        priv_key.chmod(PRIVATE_KEY_FILE_MODE)

    pub_text = run_checked(["ssh-keygen", "-y", "-f", str(priv_key)])

    auth_file.parent.mkdir(parents=True, exist_ok=True)
    if auth_file.exists():
        old = auth_file.read_text(encoding="utf-8")
        if old == pub_text:
            return

    print(f"Writing {auth_file} from {priv_key}")

    atomic_write_text(auth_file, pub_text)


def process_routers(cfg_data: ConfigData, key_dir: Path) -> None:
    for router in cfg_data.routers:
        slug = router.slug
        router_dir = ROUTERS_ROOT / slug
        dropbear_dir = router_dir / REL_DROPBEAR_AUTHORIZED_KEYS.parent
        auth_file = dropbear_dir / "authorized_keys"
        key_name = f"{ROUTER_PREFIX}_{slug}"
        key_base = key_dir / key_name

        if not router_dir.exists():
            print(f"Skipping missing router dir: {router_dir}")
            continue

        ensure_dir(dropbear_dir)
        ensure_key_and_write_pub(key_base, auth_file, key_name)


def process_servers(cfg_data: ConfigData, key_dir: Path) -> None:
    for exit_hub in cfg_data.exit_hubs:
        exit_name = exit_hub.name
        server_dir = server_exit_dir(exit_name)
        ssh_subdir = server_dir / "root" / ".ssh"
        auth_file = ssh_subdir / "authorized_keys"
        key_name = server_key_name(exit_name)
        key_base = key_dir / key_name

        if not server_dir.exists():
            print(f"Skipping missing server dir: {server_dir}")
            continue

        ensure_dir(ssh_subdir, PRIVATE_SSH_DIR_MODE)
        ensure_key_and_write_pub(key_base, auth_file, key_name)


def router_lan_host(router) -> str:
    return router.subnet.rsplit(".", 1)[0] + ".1"


def server_host_name(exit_hub: ExitHub) -> str | None:
    # Bootstrap/default server alias: prefer public listen_ip so deploy_servers.py
    # still works before overlay management is up. If there is no public endpoint
    # fall back to generated node_ip for already-bootstrapped reverse exits.
    for value in (exit_hub.listen_ip, exit_hub.exit_ip, exit_hub.node_ip):
        if value:
            return value
    return None


def server_node_host_name(exit_hub: ExitHub) -> str | None:
    return exit_hub.node_ip or None


def ssh_config_path_text(path: Path) -> str:
    """Render paths in generated ssh_config with ~/ when possible.

    The files are still created using absolute Path objects, but ssh_config is
    nicer and portable across machines/users when it contains ~/.ssh/... instead
    of /home/<user>/.ssh/... .
    """
    home = Path.home()
    try:
        rel = path.expanduser().relative_to(home)
    except ValueError:
        return str(path)
    return "~/" + rel.as_posix()


def ssh_host_block(
    *,
    alias: str,
    identity_file: Path,
    known_hosts_file: Path,
    host_name: str | None,
) -> str:
    lines = [
        f"Host {alias}",
    ]
    if host_name:
        lines.append(f"    HostName {host_name}")
    lines.extend(
        [
            "    User root",
            f"    IdentityFile {ssh_config_path_text(identity_file)}",
            "    IdentitiesOnly yes",
            f"    UserKnownHostsFile {ssh_config_path_text(known_hosts_file)}",
        ]
    )
    return "\n".join(lines) + "\n"


def build_ssh_config(cfg_data: ConfigData, key_dir: Path) -> str:
    known_hosts_file = key_dir / SSH_KNOWN_HOSTS_FILENAME
    chunks: list[str] = [
        "# Generated by tools/ensure_ssh_keys.py. Do not edit by hand.\n",
        "# Use it explicitly: ssh -F <ssh_key_dir>/config router_<name>\n\n",
        "Host *\n",
        "    UpdateHostKeys yes\n",
        "    StrictHostKeyChecking no\n",
        "\n",
    ]

    for router in cfg_data.routers:
        slug = router.slug
        alias = f"{ROUTER_PREFIX}_{slug}"
        chunks.append(
            ssh_host_block(
                alias=alias,
                host_name=router_lan_host(router),
                identity_file=key_dir / alias,
                known_hosts_file=known_hosts_file,
            )
        )
        chunks.append("\n")

    for exit_hub in cfg_data.exit_hubs:
        exit_name = exit_hub.name
        alias = server_key_name(exit_name)
        chunks.append(
            ssh_host_block(
                alias=alias,
                host_name=server_host_name(exit_hub),
                identity_file=key_dir / alias,
                known_hosts_file=known_hosts_file,
            )
        )
        chunks.append("\n")

        node_host = server_node_host_name(exit_hub)
        if node_host:
            node_alias = f"{alias}_node"
            chunks.append(
                ssh_host_block(
                    alias=node_alias,
                    host_name=node_host,
                    identity_file=key_dir / alias,
                    known_hosts_file=known_hosts_file,
                )
            )
            chunks.append("\n")

    return "".join(chunks)


def write_ssh_config(
    cfg_data: ConfigData,
    ssh_config_path: Path,
    key_dir: Path,
) -> None:
    text = build_ssh_config(cfg_data, key_dir)
    atomic_write_text(ssh_config_path, text)
    ssh_config_path.chmod(PRIVATE_KEY_FILE_MODE)
    print(f"Writing SSH config: {ssh_config_path}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Generate per-router/per-server SSH keys, authorized_keys, "
            "and deploy SSH config"
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    args = ap.parse_args(argv)

    need("ssh-keygen")

    cfg = load_json_config(Path(args.config))
    # Validate the whole config before creating/updating any key files.
    cfg_data = build_config_data(cfg)

    key_dir = deploy_ssh_dir_from_config(cfg)
    ssh_config_path = deploy_ssh_config_path_from_config(cfg)
    ensure_dir(key_dir, PRIVATE_SSH_DIR_MODE)
    print(f"Using local SSH key dir: {key_dir}")

    process_routers(cfg_data, key_dir)
    process_servers(cfg_data, key_dir)
    write_ssh_config(cfg_data, ssh_config_path, key_dir)


if __name__ == "__main__":
    main()
