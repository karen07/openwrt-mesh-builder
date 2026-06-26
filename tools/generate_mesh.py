#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .tunnel_model import mtu_uci_options
except ImportError:
    from common import *  # type: ignore
    from tunnel_model import mtu_uci_options  # type: ignore


def build_mesh_material(
    hub_cfg: dict[str, dict[str, object]],
    target_cfg: dict[str, dict[str, object]],
    server_iface_name: str,
    client_iface_name: str,
    force: bool,
) -> KeyMaterial:
    if force:
        c_priv = gen_private_key()
        s_priv = gen_private_key()
        return KeyMaterial(
            c_priv,
            public_key_from_private(c_priv),
            s_priv,
            public_key_from_private(s_priv),
        )

    server_priv = get_interface_private_key(hub_cfg, server_iface_name)
    client_priv = get_interface_private_key(target_cfg, client_iface_name)

    if server_priv and client_priv:
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if server_priv and not client_priv:
        client_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if not server_priv and client_priv:
        server_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )

    client_priv = gen_private_key()
    server_priv = gen_private_key()
    return KeyMaterial(
        client_priv,
        public_key_from_private(client_priv),
        server_priv,
        public_key_from_private(server_priv),
    )


def build_mesh_server_block(state: MeshLinkState) -> str:
    iface = uci_block(
        "interface",
        state.server_iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": state.keys.server_private,
            "listen_port": str(state.link.port),
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(state.awg),
        },
        lists={"addresses": [state.link.srv_ip4, state.link.srv_ll]},
    )
    peer = uci_block(
        state.server_peer_section_name,
        None,
        options={
            "description": f"{state.server_iface_name}.conf",
            "public_key": state.keys.client_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": str(KEEPALIVE),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_mesh_client_block(state: MeshLinkState) -> str:
    endpoint_host, endpoint_port = peer_endpoint(
        listen_ip=state.hub.listen_ip,
        port=state.link.port,
    )

    iface = uci_block(
        "interface",
        state.client_iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": state.keys.client_private,
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(state.awg),
        },
        lists={"addresses": [state.link.cli_ip4, state.link.cli_ll]},
    )
    peer = uci_block(
        state.client_peer_section_name,
        None,
        options={
            "description": f"{state.client_iface_name}.conf",
            "public_key": state.keys.server_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": str(KEEPALIVE),
            "endpoint_host": endpoint_host,
            "endpoint_port": str(endpoint_port),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_mesh_state(
    cfg: ConfigData,
    existing_all: dict[str, dict[str, dict[str, object]]],
    force: bool,
    verbose: bool,
) -> tuple[
    dict[str, str],
    dict[str, list[str]],
    dict[str, list[MeshLinkState]],
]:
    network_blocks = {router: "" for router in cfg.router_names}
    mesh_ifaces = {router: [] for router in cfg.router_names}
    hub_states: dict[str, list[MeshLinkState]] = {h.name: [] for h in cfg.mesh_hubs}
    for hub_name, target_router in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        hub_cfg = existing_all[hub.name]
        target_cfg = existing_all[target_router]
        server_iface_name = mesh_server_iface_name_for_target(target_router)
        client_iface_name = client_iface_name_for_target(cfg, target_router, hub.name)

        state = MeshLinkState(
            hub=hub,
            target_router=target_router,
            client_alias=build_mesh_client_alias(cfg, hub.name, target_router),
            server_iface_name=server_iface_name,
            client_iface_name=client_iface_name,
            server_peer_section_name=f"amneziawg_{server_iface_name}",
            client_peer_section_name=f"amneziawg_{client_iface_name}",
            link=compute_mesh_link_params(cfg, hub, target_router),
            keys=build_mesh_material(
                hub_cfg,
                target_cfg,
                server_iface_name,
                client_iface_name,
                force,
            ),
            awg=awg_for_infra_link(mesh_link_key(hub.name, target_router)),
        )

        network_blocks[hub.name] += build_mesh_server_block(state)
        network_blocks[target_router] += build_mesh_client_block(state)
        hub_states[hub.name].append(state)
        mesh_ifaces[hub.name].append(server_iface_name)
        mesh_ifaces[target_router].append(client_iface_name)

        if verbose:
            print(
                f"MESH {hub.name:<8} -> {target_router:<10} "
                f"srv_port={state.link.port:<5} "
                f"cli_port={state.link.port:<5}"
            )

    for router in mesh_ifaces:
        mesh_ifaces[router] = sorted(set(mesh_ifaces[router]))
    return network_blocks, mesh_ifaces, hub_states
