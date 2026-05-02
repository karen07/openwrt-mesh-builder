#!/usr/bin/env python3

try:
    from .common import *
    from .wg_keys import derive_public_key
    from .validate_awg_helpers import (
        find_block_by_type_and_name,
        public_key_or_die,
        require_interface_block,
        require_option,
        require_peer_block,
        validate_awg_conf_options,
        validate_awg_peer_common,
        validate_router_awg_interface_common,
    )
    from .validate_network import (
        validate_link_is_31_pair,
        validate_link_local_matches_ipv4,
    )
    from .openvpn_model import (
        check_cert_cn,
        openvpn_client_cn,
        openvpn_inline_material,
        validate_openvpn_inline_material,
        verify_key_matches_cert,
    )
    from .tunnel_model import (
        exit_hub_is_public,
        exit_route_env_key,
        router_is_public_mesh_hub,
    )
    from .default import OPENVPN_SERVER_CN
    from .validate_context import (
        validate_optional_mtu,
        validate_optional_ipip_mtu,
        vprint,
    )
    from .validate_keys import parse_tunnel_conf, require_tunnel_sections
except ImportError:
    from common import *  # type: ignore
    from wg_keys import derive_public_key  # type: ignore
    from validate_awg_helpers import (  # type: ignore
        find_block_by_type_and_name,
        public_key_or_die,
        require_interface_block,
        require_option,
        require_peer_block,
        validate_awg_conf_options,
        validate_awg_peer_common,
        validate_router_awg_interface_common,
    )
    from validate_network import (  # type: ignore
        validate_link_is_31_pair,
        validate_link_local_matches_ipv4,
    )
    from openvpn_model import (  # type: ignore
        check_cert_cn,
        openvpn_client_cn,
        openvpn_inline_material,
        validate_openvpn_inline_material,
        verify_key_matches_cert,
    )
    from tunnel_model import (  # type: ignore
        exit_hub_is_public,
        exit_route_env_key,
        router_is_public_mesh_hub,
    )
    from default import OPENVPN_SERVER_CN  # type: ignore
    from validate_context import (  # type: ignore
        validate_optional_mtu,
        validate_optional_ipip_mtu,
        vprint,
    )
    from validate_keys import parse_tunnel_conf, require_tunnel_sections  # type: ignore


def validate_mesh_pair_confs(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        hub_parsed = existing[hub.name]
        target_parsed = existing[target_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        awg = awg_for_infra_link(mesh_link_key(hub.name, target_name))
        validate_link_is_31_pair(
            link.srv_ip4, link.cli_ip4, f"mesh {hub.name}->{target_name}"
        )

        server_iface_name = mesh_server_iface_name_for_target(target_name)
        client_iface_name = client_iface_name_for_target(cfg, target_name, hub.name)
        server_peer_type = f"amneziawg_{server_iface_name}"
        client_peer_type = f"amneziawg_{client_iface_name}"

        server_iface = require_interface_block(
            hub_parsed, server_iface_name, f"mesh {hub.name}->{target_name} server"
        )
        client_iface = require_interface_block(
            target_parsed,
            client_iface_name,
            f"mesh {hub.name}->{target_name} client",
        )
        server_peer = require_peer_block(
            hub_parsed, server_peer_type, f"mesh {hub.name}->{target_name} server"
        )
        client_peer = require_peer_block(
            target_parsed,
            client_peer_type,
            f"mesh {hub.name}->{target_name} client",
        )

        server_opts = server_iface.get("options", {})
        require_option(
            server_opts,
            "listen_port",
            str(link.port),
            f"mesh {hub.name}->{target_name} server",
        )

        server_public = validate_router_awg_interface_common(
            server_iface,
            awg,
            [link.srv_ip4, link.srv_ll],
            f"mesh {hub.name}->{target_name} server iface {server_iface_name}",
        )
        client_public = validate_router_awg_interface_common(
            client_iface,
            awg,
            [link.cli_ip4, link.cli_ll],
            f"mesh {hub.name}->{target_name} client iface {client_iface_name}",
        )

        validate_awg_peer_common(
            server_peer,
            client_public,
            f"mesh {hub.name}->{target_name} server peer {server_peer_type}",
        )
        validate_awg_peer_common(
            client_peer,
            server_public,
            f"mesh {hub.name}->{target_name} client peer {client_peer_type}",
        )

        client_opts = client_peer.get("options", {})
        expected_host, expected_port = peer_endpoint(
            listen_ip=hub.listen_ip, port=link.port
        )
        require_option(
            client_opts,
            "endpoint_host",
            expected_host,
            f"mesh {hub.name}->{target_name} client peer {client_peer_type}",
        )
        require_option(
            client_opts,
            "endpoint_port",
            str(expected_port),
            f"mesh {hub.name}->{target_name} client peer {client_peer_type}",
        )


def validate_exit_ipip_iface(
    cfg: ConfigData,
    router_name: str,
    hub: ExitHub,
    router_parsed: dict[str, dict[str, object]],
) -> None:
    active_exit_names = {h.name for h in router_exit_order_hubs(cfg, router_name)}
    if hub.name not in active_exit_names:
        return

    ipip_iface_name = router_exit_ipip_iface_name(hub.name)
    ipip_iface = require_interface_block(
        router_parsed,
        ipip_iface_name,
        f"exit {hub.name}->{router_name} router ipip iface {ipip_iface_name}",
    )
    ipip_opts = ipip_iface.get("options", {})
    where = f"exit {hub.name}->{router_name} router ipip iface {ipip_iface_name}"
    require_option(ipip_opts, "proto", "ipip", where)
    require_option(
        ipip_opts, "ipaddr", f"{lan_subnet_prefix(cfg, router_name)}.1", where
    )
    require_option(ipip_opts, "peeraddr", exit_ipip_endpoint_ip(hub), where)
    require_option(ipip_opts, "nohostroute", "1", where)
    validate_optional_ipip_mtu(ipip_opts.get("mtu"), where)


def validate_exit_pair_confs(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for hub in cfg.exit_hubs:
        for router_name in cfg.router_names:
            router_parsed = existing[router_name]
            validate_exit_ipip_iface(cfg, router_name, hub, router_parsed)

            if exit_hub_is_public(hub):
                link = compute_exit_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_link_key(hub.name, router_name))
                validate_link_is_31_pair(
                    link.srv_ip4, link.cli_ip4, f"exit {hub.name}->{router_name}"
                )
                router_iface_name = exit_out_iface_name(hub.name)
                router_peer_type = f"amneziawg_{router_iface_name}"
                router_iface = require_interface_block(
                    router_parsed,
                    router_iface_name,
                    f"exit-out {router_name}->{hub.name} router",
                )
                router_peer = require_peer_block(
                    router_parsed,
                    router_peer_type,
                    f"exit-out {router_name}->{hub.name} router",
                )
                router_public = validate_router_awg_interface_common(
                    router_iface,
                    awg,
                    [link.cli_ip4, link.cli_ll],
                    f"exit-out {router_name}->{hub.name} iface {router_iface_name}",
                )
                conf_path = server_client_conf_path(
                    hub.name, build_exit_client_alias(cfg, hub.name, router_name)
                )
                conf = parse_tunnel_conf(conf_path)
                require_tunnel_sections(conf, conf_path, {"Interface", "Peer"})
                server_iface = conf.get("Interface", {})
                server_peer = conf.get("Peer", {})
                server_priv = server_iface.get("PrivateKey")
                if not server_priv:
                    die(f"{conf_path}: missing PrivateKey")
                server_public = public_key_or_die(server_priv, str(conf_path))
                validate_awg_peer_common(
                    router_peer,
                    server_public,
                    f"exit-out {router_name}->{hub.name} peer {router_peer_type}",
                )
                router_peer_opts = router_peer.get("options", {})
                expected_host, expected_port = peer_endpoint(
                    listen_ip=hub.listen_ip, port=link.port
                )
                require_option(
                    router_peer_opts,
                    "endpoint_host",
                    expected_host,
                    f"exit-out {router_name}->{hub.name} peer {router_peer_type}",
                )
                require_option(
                    router_peer_opts,
                    "endpoint_port",
                    str(expected_port),
                    f"exit-out {router_name}->{hub.name} peer {router_peer_type}",
                )
                require_option(
                    server_peer,
                    "PublicKey",
                    router_public,
                    f"exit-out {router_name}->{hub.name} server peer {conf_path}",
                )

            if router_is_public_mesh_hub(cfg, router_name):
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                key = exit_reverse_link_key(hub.name, router_name)
                awg = awg_for_infra_link(key)
                validate_link_is_31_pair(
                    link.srv_ip4,
                    link.cli_ip4,
                    f"exit-reverse {hub.name}->{router_name}",
                )
                router_iface_name = exit_in_iface_name(hub.name)
                router_peer_type = f"amneziawg_{router_iface_name}"
                router_iface = require_interface_block(
                    router_parsed,
                    router_iface_name,
                    f"exit-in {hub.name}->{router_name} router",
                )
                router_peer = require_peer_block(
                    router_parsed,
                    router_peer_type,
                    f"exit-in {hub.name}->{router_name} router",
                )
                router_public = validate_router_awg_interface_common(
                    router_iface,
                    awg,
                    [link.srv_ip4, link.srv_ll],
                    f"exit-in {hub.name}->{router_name} iface {router_iface_name}",
                )
                require_option(
                    router_iface.get("options", {}),
                    "listen_port",
                    str(link.port),
                    f"exit-in {hub.name}->{router_name} iface {router_iface_name}",
                )
                conf_path = server_client_conf_path(
                    hub.name,
                    build_exit_reverse_client_alias(cfg, hub.name, router_name),
                )
                conf = parse_tunnel_conf(conf_path)
                require_tunnel_sections(conf, conf_path, {"Interface", "Peer"})
                server_iface = conf.get("Interface", {})
                server_peer = conf.get("Peer", {})
                server_priv = server_iface.get("PrivateKey")
                if not server_priv:
                    die(f"{conf_path}: missing PrivateKey")
                server_public = public_key_or_die(server_priv, str(conf_path))
                validate_awg_peer_common(
                    router_peer,
                    server_public,
                    f"exit-in {hub.name}->{router_name} peer {router_peer_type}",
                )
                if "endpoint_host" in router_peer.get("options", {}):
                    die(f"exit-in {hub.name}->{router_name}: unexpected endpoint_host")
                if "endpoint_port" in router_peer.get("options", {}):
                    die(f"exit-in {hub.name}->{router_name}: unexpected endpoint_port")
                require_option(
                    server_peer,
                    "PublicKey",
                    router_public,
                    f"exit-in {hub.name}->{router_name} server peer {conf_path}",
                )


# ============================================================
# VALIDATION: VIRTUAL DEPLOY INVARIANTS
# ============================================================


# ============================================================
# MAIN
# ============================================================
