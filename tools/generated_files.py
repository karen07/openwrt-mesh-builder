#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .config_model import ConfigData, ExitHub
    from .default import (
        AWG_SERVER_NETWORK_SERVICE_NAME,
        PROTOCOL_AMNEZIAWG,
        PROTOCOL_OPENVPN,
        PROTOCOL_WIREGUARD,
        REL_DIRECT_IPSET,
        REL_DIRECT_STATIC_IPSET,
        REL_DROPBEAR_AUTHORIZED_KEYS,
        REL_RUNTIME_ENV,
        SERVER_TEMPLATE_DIR,
    )
    from .layout import (
        router_dir,
        router_openvpn_ca_dir,
        router_openvpn_clients_dir,
        router_openvpn_root,
        router_openvpn_server_conf_path,
        router_path,
        router_wireguard_clients_dir,
        router_wireguard_root,
        server_amneziawg_dir,
        server_babeld_conf_path,
        server_client_conf_path,
        server_exit_dir,
        server_path,
    )
    from .link_alias_model import (
        build_exit_client_alias,
        build_exit_exit_alias,
        build_exit_reverse_client_alias,
    )
    from .link_model import exit_exit_peer_names_for_hub
    from .process import die
    from .tunnel_model import exit_hub_is_public
    from .sync_rules import SYNC_COPY_DIRS, SYNC_COPY_FILES, SYNC_MERGE_FILES
except ImportError:
    from config_model import ConfigData, ExitHub  # type: ignore
    from default import (  # type: ignore
        AWG_SERVER_NETWORK_SERVICE_NAME,
        PROTOCOL_AMNEZIAWG,
        PROTOCOL_OPENVPN,
        PROTOCOL_WIREGUARD,
        REL_DIRECT_IPSET,
        REL_DIRECT_STATIC_IPSET,
        REL_DROPBEAR_AUTHORIZED_KEYS,
        REL_RUNTIME_ENV,
        SERVER_TEMPLATE_DIR,
    )
    from layout import (  # type: ignore
        router_dir,
        router_openvpn_ca_dir,
        router_openvpn_clients_dir,
        router_openvpn_root,
        router_openvpn_server_conf_path,
        router_path,
        router_wireguard_clients_dir,
        router_wireguard_root,
        server_amneziawg_dir,
        server_babeld_conf_path,
        server_client_conf_path,
        server_exit_dir,
        server_path,
    )
    from link_alias_model import (  # type: ignore
        build_exit_client_alias,
        build_exit_exit_alias,
        build_exit_reverse_client_alias,
    )
    from link_model import exit_exit_peer_names_for_hub  # type: ignore
    from process import die  # type: ignore
    from tunnel_model import exit_hub_is_public  # type: ignore
    from sync_rules import SYNC_COPY_DIRS, SYNC_COPY_FILES, SYNC_MERGE_FILES  # type: ignore


def exit_exit_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return sorted(
        build_exit_exit_alias(cfg, hub.name, peer_name)
        for peer_name in exit_exit_peer_names_for_hub(cfg, hub)
    )


def exit_direct_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    if not exit_hub_is_public(hub):
        return []
    return [build_exit_client_alias(cfg, hub.name, name) for name in cfg.router_names]


def exit_reverse_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return [
        build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
        for mesh_hub in cfg.mesh_hubs
    ]


def exit_server_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return sorted(
        set(exit_direct_aliases_for_hub(cfg, hub))
        | set(exit_reverse_aliases_for_hub(cfg, hub))
        | set(exit_exit_aliases_for_hub(cfg, hub))
    )


def expected_sync_router_paths() -> tuple[set[Path], set[Path]]:
    exact = set(SYNC_COPY_FILES) | set(SYNC_MERGE_FILES)
    dirs = set(SYNC_COPY_DIRS)
    return exact, dirs


def expected_router_generated_exact_paths(
    cfg: ConfigData,
    router_name: str,
) -> set[Path]:
    root = router_dir(cfg, router_name)
    expected: set[Path] = {
        router_path(cfg, router_name, "network").relative_to(root),
        router_path(cfg, router_name, "firewall").relative_to(root),
        router_path(cfg, router_name, "bootstrap").relative_to(root),
        router_path(cfg, router_name, "babeld").relative_to(root),
        REL_DROPBEAR_AUTHORIZED_KEYS,
        REL_DIRECT_STATIC_IPSET,
        REL_RUNTIME_ENV,
        REL_DIRECT_IPSET,
    }

    if any(g.protocol == PROTOCOL_OPENVPN for g in cfg.access.get(router_name, [])):
        expected.add(router_path(cfg, router_name, "openvpn_uci").relative_to(root))

    for group in cfg.access.get(router_name, []):
        if group.protocol == PROTOCOL_OPENVPN:
            ca_dir = router_openvpn_ca_dir(cfg, router_name, group.name).relative_to(
                root
            )
            clients_dir = router_openvpn_clients_dir(
                cfg, router_name, group.name
            ).relative_to(root)

            expected.add(
                router_openvpn_server_conf_path(
                    cfg, router_name, group.name
                ).relative_to(root)
            )
            expected |= {
                ca_dir / "ca.key",
                ca_dir / "ca.pem",
            }

            for user in group.users:
                expected.add(clients_dir / f"{user}.ovpn")

        elif group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
            clients_dir = router_wireguard_clients_dir(
                cfg, router_name, group.name
            ).relative_to(root)

            for user in group.users:
                expected.add(clients_dir / f"{user}.conf")

    return expected


def expected_server_exact_paths(cfg: ConfigData) -> set[Path]:
    expected: set[Path] = set()

    example_root = SERVER_TEMPLATE_DIR
    template_rel_files: set[Path] = set()
    if example_root.exists():
        for p in example_root.rglob("*"):
            if p.is_file():
                expected.add(p)
                template_rel_files.add(p.relative_to(example_root))

    for hub in cfg.exit_hubs:
        exit_root = server_exit_dir(hub.name)

        for rel in template_rel_files:
            expected.add(exit_root / rel)

        expected |= {
            server_babeld_conf_path(hub.name),
            exit_root / "etc/awg-server.env",
            exit_root / "etc/ipsets/direct-static.txt",
            exit_root / "etc/ipsets/direct.txt",
            exit_root / "root/.ssh/authorized_keys",
        }

        expected |= {
            server_client_conf_path(hub.name, alias)
            for alias in exit_server_aliases_for_hub(cfg, hub)
        }

    return expected


def validate_generated_files_exist(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        for kind in ("network", "firewall", "babeld", "bootstrap"):
            path = router_path(cfg, router_name, kind)
            if not path.exists():
                die(f"missing generated file: {path}")

        expected_wg_ifaces = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}
        }
        wg_root = router_wireguard_root(cfg, router_name)
        if wg_root.exists():
            actual_wg_ifaces = {p.name for p in wg_root.iterdir() if p.is_dir()}
            stale = actual_wg_ifaces - expected_wg_ifaces
            if stale:
                die(
                    f"{wg_root}: stale WireGuard access dirs: "
                    f"{', '.join(sorted(stale))}"
                )

        expected_ovpn_ifaces = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.protocol == PROTOCOL_OPENVPN
        }
        ovpn_root = router_openvpn_root(cfg, router_name)
        if ovpn_root.exists():
            actual_ovpn_ifaces = {p.name for p in ovpn_root.iterdir() if p.is_dir()}
            stale = actual_ovpn_ifaces - expected_ovpn_ifaces
            if stale:
                die(
                    f"{ovpn_root}: stale OpenVPN access dirs: "
                    f"{', '.join(sorted(stale))}"
                )

        for group in cfg.access.get(router_name, []):
            if group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
                clients_dir = router_wireguard_clients_dir(cfg, router_name, group.name)
                expected_files = {f"{user}.conf" for user in group.users}
                if not clients_dir.exists():
                    die(f"missing generated WG-like clients dir: {clients_dir}")
                actual_files = {p.name for p in clients_dir.iterdir() if p.is_file()}
                stale = actual_files - expected_files
                if stale:
                    die(
                        f"{clients_dir}: stale WG-like client files: "
                        f"{', '.join(sorted(stale))}"
                    )
                for filename in expected_files:
                    path = clients_dir / filename
                    if not path.exists():
                        die(f"missing generated WG-like client config: {path}")

            elif group.protocol == PROTOCOL_OPENVPN:
                for path in (
                    router_openvpn_ca_dir(cfg, router_name, group.name) / "ca.pem",
                    router_openvpn_server_conf_path(cfg, router_name, group.name),
                ):
                    if not path.exists():
                        die(f"missing generated OpenVPN file: {path}")

                clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
                expected_files = {f"{user}.ovpn" for user in group.users}
                if not clients_dir.exists():
                    die(f"missing generated OpenVPN clients dir: {clients_dir}")
                actual_files = {p.name for p in clients_dir.iterdir() if p.is_file()}
                stale = actual_files - expected_files
                if stale:
                    die(
                        f"{clients_dir}: stale OpenVPN client files: "
                        f"{', '.join(sorted(stale))}"
                    )
                for filename in expected_files:
                    path = clients_dir / filename
                    if not path.exists():
                        die(f"missing generated OpenVPN client config: {path}")

    for hub in cfg.exit_hubs:
        server_files_root = server_exit_dir(hub.name) / "files"
        if server_files_root.exists():
            die(
                f"{server_files_root}: unexpected server overlay dir; "
                f"use {server_exit_dir(hub.name) / 'etc'} and "
                f"{server_exit_dir(hub.name) / 'root'}"
            )

        for path in (
            server_babeld_conf_path(hub.name),
            server_path(hub.name, "etc", "awg-server.env"),
            server_path(hub.name, "etc", "ipsets", "direct-static.txt"),
            server_path(hub.name, "etc", "ipsets", "direct.txt"),
            server_path(
                hub.name,
                "etc",
                "systemd",
                "system",
                AWG_SERVER_NETWORK_SERVICE_NAME,
            ),
            server_path(hub.name, "root", ".ssh", "authorized_keys"),
        ):
            if not path.exists():
                die(f"missing generated Exit hub server file: {path}")

        server_dir = server_amneziawg_dir(hub.name)
        expected_files = {
            f"{alias}.conf" for alias in exit_server_aliases_for_hub(cfg, hub)
        }
        if not server_dir.exists():
            die(f"missing generated Exit hub server config dir: {server_dir}")
        actual_files = {p.name for p in server_dir.iterdir() if p.is_file()}
        stale = actual_files - expected_files
        if stale:
            die(
                f"{server_dir}: stale Exit hub server client configs: "
                f"{', '.join(sorted(stale))}"
            )
        for filename in expected_files:
            path = server_dir / filename
            if not path.exists():
                die(f"missing generated Exit hub client server config: {path}")
