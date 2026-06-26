#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .openvpn_model import build_openvpn_access_interface_block
    from .tunnel_model import mtu_uci_options
except ImportError:
    from common import *  # type: ignore
    from openvpn_model import build_openvpn_access_interface_block  # type: ignore
    from tunnel_model import mtu_uci_options  # type: ignore


def build_access_interface_block(
    iface_name: str,
    protocol: str,
    awg: AwgOptions | None,
    server_private: str,
    server_ip4: str,
    port: int,
) -> str:
    options = {
        "proto": protocol,
        "private_key": server_private,
        "listen_port": str(port),
        "defaultroute": "0",
        **mtu_uci_options(),
    }
    if protocol == PROTOCOL_AMNEZIAWG:
        if awg is None:
            die(f"access {iface_name}: awg options are required for amneziawg")
        options.update(awg_uci_options(awg))

    return (
        uci_block(
            "interface",
            iface_name,
            options=options,
            lists={"addresses": [server_ip4]},
        )
        + "\n"
    )


def build_access_peer_block(state: AccessPeerState) -> str:
    prefix = (
        PROTOCOL_AMNEZIAWG
        if state.protocol == PROTOCOL_AMNEZIAWG
        else PROTOCOL_WIREGUARD
    )
    return (
        uci_block(
            f"{prefix}_{state.iface}",
            None,
            options={
                "public_key": state.client_public,
                "description": f"{state.user_name}.conf",
                "route_allowed_ips": "1",
                "persistent_keepalive": str(KEEPALIVE),
            },
            lists={"allowed_ips": [state.client_ip4]},
        )
        + "\n"
    )


def build_access_state(
    cfg: ConfigData,
    existing_all: dict[str, dict[str, dict[str, object]]],
    access_groups: dict[str, list[AccessGroup]],
    force: bool,
    verbose: bool,
) -> tuple[dict[str, str], dict[str, list[AccessPeerState]], set[str]]:
    network_blocks = {router: "" for router in access_groups}
    states_by_router: dict[str, list[AccessPeerState]] = {
        router: [] for router in access_groups
    }
    managed_names: set[str] = set()

    for router_name, groups in access_groups.items():
        cfg_by_name = existing_all[router_name]

        for group in groups:
            managed_names.add(group.name)

            if group.protocol == PROTOCOL_OPENVPN:
                network_blocks[router_name] += build_openvpn_access_interface_block(
                    group.name
                )
                if verbose:
                    print(
                        f"ACCESS {router_name:<8} {group.name:<12} "
                        f"name={group.name:<16} protocol=openvpn subnet={group.subnet}.0/24"
                    )
                continue

            server_ip4 = host_ip_in_prefix(
                group.subnet, ACCESS_SERVER_HOST, ACCESS_SUBNET_CIDR
            )

            existing_iface_priv = get_interface_private_key(cfg_by_name, group.name)
            if existing_iface_priv is not None and not force:
                server_priv = existing_iface_priv
            else:
                server_priv = gen_private_key()

            server_pub = public_key_from_private(server_priv)

            network_blocks[router_name] += build_access_interface_block(
                group.name,
                group.protocol,
                group.awg,
                server_priv,
                server_ip4,
                group.port,
            )

            for idx, user_name in enumerate(group.users):
                host = ACCESS_HOST_START + idx
                client_ip4 = host_ip_in_prefix(group.subnet, host, CLIENT_TUNNEL_CIDR)

                if force:
                    client_priv = gen_private_key()
                    client_pub = public_key_from_private(client_priv)
                else:
                    client_conf = (
                        router_wireguard_clients_dir(cfg, router_name, group.name)
                        / f"{user_name}.conf"
                    )
                    old_priv, old_pub_from_conf = parse_existing_tunnel_conf(
                        client_conf
                    )

                    peer_block = find_access_peer_block(
                        cfg_by_name, group.name, user_name, group.protocol
                    )
                    old_pub_from_uci = None
                    if peer_block:
                        old_pub_from_uci = peer_block.get("options", {}).get(
                            "public_key"
                        )

                    if old_priv:
                        client_priv = old_priv
                        client_pub = (
                            old_pub_from_uci
                            or old_pub_from_conf
                            or public_key_from_private(client_priv)
                        )
                    else:
                        client_priv = gen_private_key()
                        client_pub = public_key_from_private(client_priv)

                state = AccessPeerState(
                    router_name=router_name,
                    iface=group.name,
                    user_name=user_name,
                    client_ip4=client_ip4,
                    server_ip4=server_ip4,
                    subnet=group.subnet,
                    port=group.port,
                    protocol=group.protocol,
                    awg=group.awg,
                    client_private=client_priv,
                    client_public=client_pub,
                    server_private=server_priv,
                    server_public=server_pub,
                )

                network_blocks[router_name] += build_access_peer_block(state)
                states_by_router[router_name].append(state)

                if verbose:
                    print(
                        f"ACCESS {router_name:<8} {group.name:<12} "
                        f"protocol={group.protocol:<10} user={user_name:<12} ip={client_ip4}"
                    )

    return network_blocks, states_by_router, managed_names
