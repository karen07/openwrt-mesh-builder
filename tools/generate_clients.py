#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .access_model import router_public_host_for_access
    from .openvpn_model import (
        build_openvpn_client_conf,
        ensure_openvpn_client_material,
        ensure_openvpn_server_conf,
        reconcile_router_openvpn_dirs,
        reconcile_router_openvpn_layout,
        render_openvpn_uci_text,
    )
except ImportError:
    from common import *  # type: ignore
    from access_model import router_public_host_for_access  # type: ignore
    from openvpn_model import (  # type: ignore
        build_openvpn_client_conf,
        ensure_openvpn_client_material,
        ensure_openvpn_server_conf,
        reconcile_router_openvpn_dirs,
        reconcile_router_openvpn_layout,
        render_openvpn_uci_text,
    )


def update_openvpn_uci(
    cfg: ConfigData,
    router_name: str,
    groups: list[AccessGroup],
    extra_blocks: list[str] | None = None,
) -> None:
    path = router_path(cfg, router_name, "openvpn_uci")
    ovpn_groups = [g for g in groups if g.protocol == PROTOCOL_OPENVPN]
    text = render_openvpn_uci_text(ovpn_groups, extra_blocks=extra_blocks)
    if not text:
        rm(path)
        return
    write(path, text)


def generate_openvpn_access(cfg: ConfigData, force: bool, verbose: bool) -> None:
    for router_name, groups in cfg.access.items():
        ovpn_groups = [g for g in groups if g.protocol == PROTOCOL_OPENVPN]
        keep_ifaces = {g.name for g in ovpn_groups}

        reconcile_router_openvpn_dirs(cfg, router_name, keep_ifaces)

        for group in ovpn_groups:
            reconcile_router_openvpn_layout(cfg, router_name, group.name)
            ensure_openvpn_server_conf(
                cfg,
                router_name,
                group,
                dns_ip=f"{lan_subnet_prefix(cfg, router_name)}.1",
                force=force,
            )

            if verbose:
                print(
                    f"OPENVPN {router_name:<8} iface={group.name:<16} "
                    f"port={group.port:<5} subnet={group.subnet}.0/24"
                )


def generate_openvpn_client_files(cfg: ConfigData, force: bool, verbose: bool) -> None:
    for router_name, groups in cfg.access.items():
        for group in groups:
            if group.protocol != PROTOCOL_OPENVPN:
                continue

            reconcile_router_openvpn_layout(cfg, router_name, group.name)

            ca_pem = router_openvpn_ca_dir(cfg, router_name, group.name) / "ca.pem"
            remote_host = router_public_host_for_access(cfg, router_name)
            clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
            clients_dir.mkdir(parents=True, exist_ok=True)

            keep_files = {f"{user}.ovpn" for user in group.users}
            for child in clients_dir.iterdir():
                if child.is_file() and child.name not in keep_files:
                    rm(child)

            for idx, user_name in enumerate(group.users, start=1):
                key_text, cert_text = ensure_openvpn_client_material(
                    cfg=cfg,
                    router_name=router_name,
                    iface_name=group.name,
                    user_name=user_name,
                    client_index_1based=idx,
                    force=force,
                )

                write(
                    clients_dir / f"{user_name}.ovpn",
                    build_openvpn_client_conf(
                        remote_host=remote_host,
                        remote_port=group.port,
                        ca_pem_text=read(ca_pem),
                        cert_pem_text=cert_text,
                        key_pem_text=key_text,
                    ),
                )

                if verbose:
                    print(
                        f"OPENVPN-CLIENT {router_name:<8} iface={group.name:<16} "
                        f"user={user_name:<12} remote={remote_host}:{group.port}"
                    )


# ============================================================
# ACCESS WG-LIKE CLIENT FILE HELPERS
# ============================================================


def build_wireguard_client_conf(
    client_private: str,
    client_ip4: str,
    server_public: str,
    remote_host: str,
    remote_port: int,
    dns_ip: str,
    awg: AwgOptions | None = None,
) -> str:
    awg_text = ""
    if awg is not None:
        awg_text = "".join(f"{line}\n" for line in awg_conf_lines(awg))

    return (
        "[Interface]\n"
        f"PrivateKey = {stored_key_material(client_private)}\n"
        f"Address = {client_ip4}\n"
        f"DNS = {dns_ip}\n"
        + (f"MTU = {TUNNEL_MTU}\n" if TUNNEL_MTU is not None else "")
        + awg_text
        + "\n"
        "[Peer]\n"
        f"PublicKey = {server_public}\n"
        f"Endpoint = {remote_host}:{remote_port}\n"
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}\n"
        f"PersistentKeepalive = {KEEPALIVE}\n"
    )


def reconcile_router_wireguard_dirs(
    cfg: ConfigData,
    router_name: str,
    keep_iface_names: set[str],
) -> None:
    root = router_wireguard_root(cfg, router_name)

    if not keep_iface_names:
        rm(root)
        return

    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir() and child.name not in keep_iface_names:
            rm(child)


def generate_wireguard_client_files(
    cfg: ConfigData,
    states_by_router: dict[str, list[AccessPeerState]],
    verbose: bool,
) -> None:
    for router_name, states in states_by_router.items():
        access_ifaces = {st.iface for st in states}
        reconcile_router_wireguard_dirs(cfg, router_name, access_ifaces)

        states_by_iface: dict[str, list[AccessPeerState]] = {}
        for st in states:
            states_by_iface.setdefault(st.iface, []).append(st)

        for iface_name, iface_states in states_by_iface.items():
            iface_dir = router_wireguard_iface_dir(cfg, router_name, iface_name)
            clients_dir = router_wireguard_clients_dir(cfg, router_name, iface_name)
            clients_dir.mkdir(parents=True, exist_ok=True)

            keep_files = {f"{st.user_name}.conf" for st in iface_states}
            for child in clients_dir.iterdir():
                if child.is_file() and child.name not in keep_files:
                    rm(child)

            remote_host = router_public_host_for_access(cfg, router_name)
            dns_ip = f"{lan_subnet_prefix(cfg, router_name)}.1"

            for st in iface_states:
                write(
                    clients_dir / f"{st.user_name}.conf",
                    build_wireguard_client_conf(
                        client_private=st.client_private,
                        client_ip4=st.client_ip4,
                        server_public=st.server_public,
                        remote_host=remote_host,
                        remote_port=st.port,
                        dns_ip=dns_ip,
                        awg=st.awg,
                    ),
                )

                if verbose:
                    label = (
                        "AWG-CLIENT"
                        if st.protocol == PROTOCOL_AMNEZIAWG
                        else "WG-CLIENT"
                    )
                    print(
                        f"{label} {router_name:<8} iface={iface_name:<16} "
                        f"user={st.user_name:<12} remote={remote_host}:{st.port} "
                        f"dir={iface_dir}"
                    )
