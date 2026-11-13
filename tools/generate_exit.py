#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

from .awg_model import awg_conf_lines, awg_uci_options, peer_endpoint
from .config_exit_model import (
    lan_subnet_prefix,
    router_exit_ipip_iface_name,
    router_required_exit_hubs,
    routing_exit_policy_ids,
)
from .config_model import (
    AwgOptions,
    ConfigData,
    ExitExitLinkParams,
    ExitHub,
    KeyMaterial,
    LinkParams,
)
from .default import (
    DEFAULT_ALLOWED_IPS,
    DEFAULT_ALLOWED_IPS_TEXT,
    EXIT_RULE_PRIORITY,
    PROTOCOL_AMNEZIAWG,
)
from .layout import server_client_conf_path
from .link_alias_model import build_exit_exit_alias
from .link_model import (
    exit_exit_link_pair_for_hubs,
    exit_in_iface_name,
    exit_out_iface_name,
)
from .materials import (
    gen_private_key,
    parse_existing_tunnel_conf,
    public_key_from_private,
    stored_key_material,
)
from .net_model import exit_ipip_endpoint_ip
from .network_config import get_interface_private_key, uci_block
from .process import die
from .tunnel_model import (
    exit_hub_is_public,
    ipip_mtu_uci_options,
    maybe_mtu_conf_line,
    mtu_uci_options,
)


def build_material_for_exit(
    router_name: str,
    hub: ExitHub,
    client_alias: str,
    router_iface_name: str,
    router_cfg: dict[str, dict[str, object]],
    force: bool,
) -> KeyMaterial:
    _ = router_name
    if force:
        c_priv = gen_private_key()
        s_priv = gen_private_key()
        return KeyMaterial(
            c_priv,
            public_key_from_private(c_priv),
            s_priv,
            public_key_from_private(s_priv),
        )

    client_priv = get_interface_private_key(router_cfg, router_iface_name)
    server_conf = server_client_conf_path(hub.name, client_alias)
    server_priv, _ = parse_existing_tunnel_conf(server_conf)

    if client_priv and server_priv:
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if client_priv and not server_priv:
        server_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if not client_priv and server_priv:
        client_priv = gen_private_key()
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


def build_material_for_exit_reverse(
    hub: ExitHub,
    client_alias: str,
    router_iface_name: str,
    router_cfg: dict[str, dict[str, object]],
    force: bool,
) -> KeyMaterial:
    # For ExitXXIn, the OpenWrt side is the listener/server and the exit-side
    # .conf is the dialer/client. Keep the same KeyMaterial meaning:
    # client_* belongs to the exit-side .conf, server_* belongs to OpenWrt.
    if force:
        c_priv = gen_private_key()
        s_priv = gen_private_key()
        return KeyMaterial(
            c_priv,
            public_key_from_private(c_priv),
            s_priv,
            public_key_from_private(s_priv),
        )

    server_priv = get_interface_private_key(router_cfg, router_iface_name)

    server_conf = server_client_conf_path(hub.name, client_alias)
    client_priv, _ = parse_existing_tunnel_conf(server_conf)

    if client_priv and server_priv:
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if client_priv and not server_priv:
        server_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if not client_priv and server_priv:
        client_priv = gen_private_key()
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


def build_exit_out_network_interface_block(
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    iface_name = exit_out_iface_name(hub.name)
    endpoint_host, endpoint_port = peer_endpoint(
        listen_ip=hub.listen_ip,
        port=link.port,
    )

    iface = uci_block(
        "interface",
        iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": keys.client_private,
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(awg),
        },
        lists={"addresses": [link.cli_ip4, link.cli_ll]},
    )
    peer = uci_block(
        f"amneziawg_{iface_name}",
        None,
        options={
            "description": f"{iface_name}.conf",
            "public_key": keys.server_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": awg.persistent_keepalive,
            "endpoint_host": endpoint_host,
            "endpoint_port": str(endpoint_port),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_exit_in_network_interface_block(
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    iface_name = exit_in_iface_name(hub.name)
    iface = uci_block(
        "interface",
        iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": keys.server_private,
            "listen_port": str(link.port),
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(awg),
        },
        lists={"addresses": [link.srv_ip4, link.srv_ll]},
    )
    peer = uci_block(
        f"amneziawg_{iface_name}",
        None,
        options={
            "description": f"{iface_name}.conf",
            "public_key": keys.client_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": awg.persistent_keepalive,
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_exit_ipip_interface_block(
    cfg: ConfigData,
    router_name: str,
    hub: ExitHub,
) -> str:
    # Outer source is the router LAN gateway IP. It is already redistributed
    # by Babel, so the exit can route replies/control traffic back if needed.
    return (
        uci_block(
            "interface",
            router_exit_ipip_iface_name(hub.name),
            options={
                "proto": "ipip",
                "ipaddr": f"{lan_subnet_prefix(cfg, router_name)}.1",
                "peeraddr": exit_ipip_endpoint_ip(hub),
                "nohostroute": "1",
                **ipip_mtu_uci_options(),
            },
        )
        + "\n"
    )


def build_exit_rule_network_blocks(cfg: ConfigData, router_name: str) -> str:
    # Provision a policy route for every exit on every router, irrespective of
    # exit_order and the initial per-device routing rules.
    policy_ids = routing_exit_policy_ids(cfg)
    blocks: list[str] = []

    if cfg.exit_hubs:
        # UID 4453 is the DoH service user. Normal LAN packets use fwmark 10000.
        # A terminal guard prevents missing exit routes from falling to main.
        # For DoH the guard is active only while global mode is EXIT_FAIL_CLOSED.
        initial_mode = cfg.exit_routes_by_router[router_name].mode
        blocks.extend(
            [
                uci_block(
                    "rule",
                    options={"priority": "90", "lookup": "10000", "uidrange": "4453"},
                ),
                uci_block(
                    "rule",
                    options={
                        "priority": "91",
                        "uidrange": "4453",
                        "action": "unreachable",
                        **(
                            {}
                            if initial_mode == "EXIT_FAIL_CLOSED"
                            else {"disabled": "1"}
                        ),
                    },
                ),
                uci_block(
                    "rule",
                    options={"priority": "100", "lookup": "10000", "mark": "10000"},
                ),
            ]
        )

    # The global route is fixed infrastructure. The runtime service only
    # changes its selected interface and enabled state; it never creates it.
    required_hubs = router_required_exit_hubs(cfg, router_name)
    if required_hubs:
        blocks.append(
            uci_block(
                "route",
                "exit10000",
                options={
                    "interface": router_exit_ipip_iface_name(required_hubs[0].name),
                    "target": "0.0.0.0/0",
                    "table": "10000",
                    "disabled": "1",
                },
            )
        )

    for hub in required_hubs:
        policy_id = policy_ids[hub.name]
        blocks.append(
            uci_block(
                "rule",
                options={
                    "priority": str(EXIT_RULE_PRIORITY),
                    "mark": str(policy_id),
                    "lookup": str(policy_id),
                },
            )
        )
        blocks.append(
            uci_block(
                "route",
                options={
                    "interface": router_exit_ipip_iface_name(hub.name),
                    "target": "0.0.0.0/0",
                    "table": str(policy_id),
                },
            )
        )

    return "\n\n".join(blocks) + ("\n" if blocks else "")


def build_server_direct_conf(
    client_alias: str,
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    _ = client_alias, hub
    lines = [
        "[Interface]",
        f"PrivateKey = {stored_key_material(keys.server_private)}",
        f"Address = {link.srv_ip4}, {link.srv_ll}",
        f"ListenPort = {link.port}",
        *maybe_mtu_conf_line(),
        *awg_conf_lines(awg),
        "Table = off",
        "",
        "[Peer]",
        f"PublicKey = {keys.client_public}",
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}",
        f"PersistentKeepalive = {awg.persistent_keepalive}",
    ]
    return "\n".join(lines) + "\n"


def build_server_reverse_conf(
    cfg: ConfigData,
    router_name: str,
    client_alias: str,
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    _ = client_alias, hub
    router_hub = cfg.mesh_hubs_by_name[router_name]
    endpoint_host, endpoint_port = peer_endpoint(
        listen_ip=router_hub.listen_ip,
        port=link.port,
    )
    lines = [
        "[Interface]",
        f"PrivateKey = {stored_key_material(keys.client_private)}",
        f"Address = {link.cli_ip4}, {link.cli_ll}",
        *maybe_mtu_conf_line(),
        *awg_conf_lines(awg),
        "Table = off",
        "",
        "[Peer]",
        f"PublicKey = {keys.server_public}",
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}",
        f"Endpoint = {endpoint_host}:{endpoint_port}",
        f"PersistentKeepalive = {awg.persistent_keepalive}",
    ]
    return "\n".join(lines) + "\n"


def exit_exit_conf_path(cfg: ConfigData, exit_name: str, peer_name: str) -> Path:
    return server_client_conf_path(
        exit_name, build_exit_exit_alias(cfg, exit_name, peer_name)
    )


def build_material_for_exit_exit(
    cfg: ConfigData, left_hub: ExitHub, right_hub: ExitHub, force: bool
) -> KeyMaterial:
    left_name, right_name = exit_exit_link_pair_for_hubs(
        cfg, left_hub.name, right_hub.name
    )
    left_conf = exit_exit_conf_path(cfg, left_name, right_name)
    right_conf = exit_exit_conf_path(cfg, right_name, left_name)

    if force:
        left_priv = gen_private_key()
        right_priv = gen_private_key()
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )

    left_priv, _ = parse_existing_tunnel_conf(left_conf)
    right_priv, _ = parse_existing_tunnel_conf(right_conf)

    if left_priv and right_priv:
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )
    if left_priv and not right_priv:
        right_priv = gen_private_key()
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )
    if not left_priv and right_priv:
        left_priv = gen_private_key()
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )

    left_priv = gen_private_key()
    right_priv = gen_private_key()
    return KeyMaterial(
        left_priv,
        public_key_from_private(left_priv),
        right_priv,
        public_key_from_private(right_priv),
    )


def build_exit_exit_server_conf(
    local_hub: ExitHub,
    peer_hub: ExitHub,
    link: ExitExitLinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    if local_hub.name == link.left_name and peer_hub.name == link.right_name:
        local_private = keys.client_private
        local_ip4 = link.left_ip4
        local_ll = link.left_ll
        local_port = link.left_port
        peer_public = keys.server_public
        peer_port = link.right_port
    elif local_hub.name == link.right_name and peer_hub.name == link.left_name:
        local_private = keys.server_private
        local_ip4 = link.right_ip4
        local_ll = link.right_ll
        local_port = link.right_port
        peer_public = keys.client_public
        peer_port = link.left_port
    else:
        die(
            f"bad exit-exit local/peer mapping: "
            f"{local_hub.name}<->{peer_hub.name} for {link.left_name}<->{link.right_name}"
        )

    peer_lines = [
        "[Peer]",
        f"PublicKey = {peer_public}",
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}",
    ]
    if exit_hub_is_public(peer_hub):
        endpoint_host, endpoint_port = peer_endpoint(
            listen_ip=peer_hub.listen_ip,
            port=peer_port,
        )
        peer_lines.append(f"Endpoint = {endpoint_host}:{endpoint_port}")
    peer_lines.append(f"PersistentKeepalive = {awg.persistent_keepalive}")

    lines = [
        "[Interface]",
        f"PrivateKey = {stored_key_material(local_private)}",
        f"Address = {local_ip4}, {local_ll}",
        f"ListenPort = {local_port}",
        *maybe_mtu_conf_line(),
        *awg_conf_lines(awg),
        "Table = off",
        "",
        *peer_lines,
    ]
    return "\n".join(lines) + "\n"
