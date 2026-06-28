#!/usr/bin/env python3
from pathlib import Path

try:
    from .common import *
    from .wg_keys import derive_public_key
    from .generated_files import exit_server_aliases_for_hub
    from .validate_awg_helpers import (
        find_block_by_type_and_name,
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
    from .validate_uci import parse_uci_file
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
        ipip_mtu_value,
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
    from generated_files import exit_server_aliases_for_hub  # type: ignore
    from validate_awg_helpers import (  # type: ignore
        find_block_by_type_and_name,
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
    from validate_uci import parse_uci_file  # type: ignore
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
        ipip_mtu_value,
        router_is_public_mesh_hub,
    )
    from default import OPENVPN_SERVER_CN  # type: ignore
    from validate_context import (  # type: ignore
        validate_optional_mtu,
        validate_optional_ipip_mtu,
        vprint,
    )
    from validate_keys import parse_tunnel_conf, require_tunnel_sections  # type: ignore


def validate_router_endpoints(
    cfg: ConfigData,
    existing: dict[str, dict[str, dict[str, object]]],
) -> None:
    for router_name in cfg.router_names:
        parsed = existing[router_name]

        for hub in cfg.exit_hubs:
            if exit_hub_is_public(hub):
                link = compute_exit_link_params(cfg, hub, router_name)
                iface = exit_out_iface_name(hub.name)
                peer = find_block_by_type_and_name(parsed, f"amneziawg_{iface}")
                if peer is None:
                    die(f"router {router_name}: missing ExitOut peer for {hub.name}")
                opts = peer.get("options", {})
                expected_host, expected_port = peer_endpoint(
                    listen_ip=hub.listen_ip,
                    port=link.port,
                )
                if opts.get("endpoint_host") != expected_host:
                    die(f"router {router_name}/{iface}: bad endpoint_host")
                if opts.get("endpoint_port") != str(expected_port):
                    die(f"router {router_name}/{iface}: bad endpoint_port")

            if router_is_public_mesh_hub(cfg, router_name):
                iface = exit_in_iface_name(hub.name)
                peer = find_block_by_type_and_name(parsed, f"amneziawg_{iface}")
                if peer is None:
                    die(f"router {router_name}: missing ExitIn peer for {hub.name}")
                opts = peer.get("options", {})
                if opts.get("endpoint_host") is not None:
                    die(f"router {router_name}/{iface}: unexpected endpoint_host")
                if opts.get("endpoint_port") is not None:
                    die(f"router {router_name}/{iface}: unexpected endpoint_port")

        for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
            # Only the client side has an Endpoint.  With spine-spine rings a
            # public spine can be the server side for one neighbour and the
            # client side for another, so do not assume every non-self hub is a
            # valid client link.
            if router_name != target_name:
                continue

            hub = cfg.mesh_hubs_by_name[hub_name]
            link = compute_mesh_link_params(cfg, hub, target_name)
            iface = client_iface_name_for_target(cfg, router_name, hub.name)
            expected_host, expected_port = peer_endpoint(
                listen_ip=hub.listen_ip,
                port=link.port,
            )
            peer = find_block_by_type_and_name(parsed, f"amneziawg_{iface}")
            if peer is None:
                die(f"router {router_name}: missing mesh peer for {iface}")
            opts = peer.get("options", {})
            if opts.get("endpoint_host") != expected_host:
                die(f"router {router_name}/{iface}: bad endpoint_host")
            if opts.get("endpoint_port") != str(expected_port):
                die(f"router {router_name}/{iface}: bad endpoint_port")


def validate_exit_server_confs(cfg: ConfigData) -> None:
    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                client_alias = build_exit_client_alias(cfg, hub.name, router_name)
                link = compute_exit_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_link_key(hub.name, router_name))
                conf_path = server_client_conf_path(hub.name, client_alias)
                conf = parse_tunnel_conf(conf_path)
                require_tunnel_sections(conf, conf_path, {"Interface", "Peer"})

                iface = conf.get("Interface", {})
                peer = conf.get("Peer", {})
                require_option(iface, "ListenPort", str(link.port), str(conf_path))
                require_option(
                    iface,
                    "Address",
                    f"{link.srv_ip4}, {link.srv_ll}",
                    str(conf_path),
                )
                validate_optional_mtu(iface.get("MTU"), str(conf_path))
                validate_awg_conf_options(iface, awg, str(conf_path))
                require_option(iface, "Table", "off", str(conf_path))
                require_option(
                    peer, "AllowedIPs", DEFAULT_ALLOWED_IPS_TEXT, str(conf_path)
                )
                if "Endpoint" in peer:
                    die(f"{conf_path}: unexpected Endpoint")
                require_option(
                    peer, "PersistentKeepalive", str(KEEPALIVE), str(conf_path)
                )

        for router_name in cfg.mesh_hubs_by_name:
            client_alias = build_exit_reverse_client_alias(cfg, hub.name, router_name)
            link = compute_exit_reverse_link_params(cfg, hub, router_name)
            awg = awg_for_infra_link(exit_reverse_link_key(hub.name, router_name))
            conf_path = server_client_conf_path(hub.name, client_alias)
            conf = parse_tunnel_conf(conf_path)
            require_tunnel_sections(conf, conf_path, {"Interface", "Peer"})

            iface = conf.get("Interface", {})
            peer = conf.get("Peer", {})
            require_option(
                iface, "Address", f"{link.cli_ip4}, {link.cli_ll}", str(conf_path)
            )
            if "ListenPort" in iface:
                die(f"{conf_path}: unexpected ListenPort")
            validate_optional_mtu(iface.get("MTU"), str(conf_path))
            validate_awg_conf_options(iface, awg, str(conf_path))
            require_option(iface, "Table", "off", str(conf_path))
            require_option(peer, "AllowedIPs", DEFAULT_ALLOWED_IPS_TEXT, str(conf_path))
            router_hub = cfg.mesh_hubs_by_name[router_name]
            endpoint_host, endpoint_port = peer_endpoint(
                listen_ip=router_hub.listen_ip,
                port=link.port,
            )
            require_option(
                peer, "Endpoint", f"{endpoint_host}:{endpoint_port}", str(conf_path)
            )
            require_option(peer, "PersistentKeepalive", str(KEEPALIVE), str(conf_path))

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        awg = awg_for_infra_link(exit_exit_link_key(left_hub.name, right_hub.name))

        pairs = (
            (
                left_hub,
                right_hub,
                build_exit_exit_alias(cfg, left_hub.name, right_hub.name),
                link.left_ip4,
                link.left_ll,
                link.left_port,
                link.right_port,
            ),
            (
                right_hub,
                left_hub,
                build_exit_exit_alias(cfg, right_hub.name, left_hub.name),
                link.right_ip4,
                link.right_ll,
                link.right_port,
                link.left_port,
            ),
        )
        for (
            local_hub,
            peer_hub,
            local_alias,
            local_addr,
            local_ll,
            local_port,
            peer_port,
        ) in pairs:
            conf_path = server_client_conf_path(local_hub.name, local_alias)
            conf = parse_tunnel_conf(conf_path)
            require_tunnel_sections(conf, conf_path, {"Interface", "Peer"})
            iface = conf.get("Interface", {})
            peer = conf.get("Peer", {})
            require_option(iface, "ListenPort", str(local_port), str(conf_path))
            require_option(
                iface, "Address", f"{local_addr}, {local_ll}", str(conf_path)
            )
            validate_optional_mtu(iface.get("MTU"), str(conf_path))
            validate_awg_conf_options(iface, awg, str(conf_path))
            require_option(iface, "Table", "off", str(conf_path))
            require_option(peer, "AllowedIPs", DEFAULT_ALLOWED_IPS_TEXT, str(conf_path))
            if exit_hub_is_public(peer_hub):
                endpoint_host, endpoint_port = peer_endpoint(
                    listen_ip=peer_hub.listen_ip, port=peer_port
                )
                require_option(
                    peer,
                    "Endpoint",
                    f"{endpoint_host}:{endpoint_port}",
                    str(conf_path),
                )
            elif "Endpoint" in peer:
                die(f"{conf_path}: unexpected Endpoint")
            require_option(peer, "PersistentKeepalive", str(KEEPALIVE), str(conf_path))


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        die(f"missing env file: {path}")
    result: dict[str, str] = {}
    for lineno, raw in enumerate(read(path).splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            die(f"{path}:{lineno}: expected KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            die(f"{path}:{lineno}: empty key")
        if key in result:
            die(f"{path}:{lineno}: duplicate key {key!r}")
        if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            value = value[1:-1].replace("'\"'\"'", "'")
        result[key] = value
    return result


def validate_exact_env_values(path: Path, expected: dict[str, str]) -> None:
    env = parse_env_file(path)
    actual_keys = set(env)
    expected_keys = set(expected)

    missing = sorted(expected_keys - actual_keys)
    if missing:
        die(f"{path}: missing env keys: {', '.join(missing)}")

    unexpected = sorted(actual_keys - expected_keys)
    if unexpected:
        die(f"{path}: unexpected env keys: {', '.join(unexpected)}")

    for key, value in expected.items():
        if env[key] != value:
            die(f"{path}: bad {key}: expected {value!r}, got {env[key]!r}")


def validate_server_env(cfg: ConfigData) -> None:
    for hub in cfg.exit_hubs:
        path = server_path(hub.name, "etc", "awg-server.env")
        service_names = [
            f"awg-quick@{alias}.service"
            for alias in exit_server_aliases_for_hub(cfg, hub)
        ]
        awg_services = " ".join(service_names)
        expected = {
            "SERVER_NAME": hub.name,
            "NODE_ADDR4": exit_node_addr4(hub),
            "NODE_IFACE": NODE_SERVER_IFACE,
            "LISTEN_IP": hub.listen_ip,
            "EXIT_IP": hub.exit_ip,
            "IPIP_IFACE": IPIP_SERVER_IFACE,
            "IPIP_ADDR4": exit_ipip_endpoint_addr4(hub),
            **(
                {"IPIP_MTU": str(ipip_mtu_value())}
                if ipip_mtu_value() is not None
                else {}
            ),
            "EXIT_SUBNETS": server_exit_subnets(cfg),
            "IPSET_NAME": SERVER_ENV_IPSET_NAME,
            "IPSETS_DIR": RUNTIME_IPSETS_DIR,
            "STATIC_DIRECT_NAME": RUNTIME_DIRECT_STATIC_NAME,
            "OUT_DIRECT_NAME": RUNTIME_DIRECT_OUT_NAME,
            "DIRECT_COUNTRIES": " ".join(cfg.exit_direct.countries),
            "DIRECT_ASNS": " ".join(cfg.exit_direct.asns),
            "UPDATE_IPSETS_CURL_CONNECT_TIMEOUT": str(
                UPDATE_IPSETS_CURL_CONNECT_TIMEOUT
            ),
            "UPDATE_IPSETS_CURL_MAX_TIME": str(UPDATE_IPSETS_CURL_MAX_TIME),
            "UPDATE_IPSETS_CURL_RETRY": str(UPDATE_IPSETS_CURL_RETRY),
            "AWG_SERVICES": awg_services,
            "BABELD_CONF": server_babeld_conf_remote_path(hub.name),
        }
        validate_exact_env_values(path, expected)


def expected_runtime_env_values(
    cfg: ConfigData, router_name: str | None = None
) -> dict[str, str]:
    hubs = (
        router_exit_order_hubs(cfg, router_name)
        if router_name is not None
        else [cfg.exit_hubs_by_name[name] for name in cfg.exit_order]
    )
    target_names = []
    for hub in hubs:
        key = exit_route_env_key(hub.name)
        iface = router_exit_ipip_iface_name(hub.name)
        expected_iface = f"ip{hub.name}"
        if key != hub.name or iface != expected_iface:
            die(
                f"exit hub {hub.name!r} cannot be used as an exit-route target; "
                "use a short uppercase ASCII name containing A-Z, 0-9 or _ so the IPIP interface "
                f"is {expected_iface!r}"
            )
        target_names.append(hub.name)
    expected = {
        "IPSETS_DIR": RUNTIME_IPSETS_DIR,
        "STATIC_DIRECT_NAME": RUNTIME_DIRECT_STATIC_NAME,
        "OUT_DIRECT_NAME": RUNTIME_DIRECT_OUT_NAME,
        "DIRECT_COUNTRIES": " ".join(cfg.exit_direct.countries),
        "DIRECT_ASNS": " ".join(cfg.exit_direct.asns),
        "CHECK_DOH_DOMAIN": CHECK_DOH_DOMAIN,
        "CHECK_DOH_INTERVAL": str(CHECK_DOH_INTERVAL),
        "CHECK_DOH_RESOLV": CHECK_DOH_RESOLV,
        "CHECK_DOH_RESOLV_WAIT_MAX": str(CHECK_DOH_RESOLV_WAIT_MAX),
        "CHECK_DOH_PROVIDER_DOMAINS": " ".join(CHECK_DOH_PROVIDER_DOMAINS),
        "EXIT_ROUTE_TABLE": str(EXIT_ROUTE_TABLE),
        "EXIT_ROUTE_INTERVAL": str(EXIT_ROUTE_INTERVAL),
        "UPDATE_IPSETS_CURL_CONNECT_TIMEOUT": str(UPDATE_IPSETS_CURL_CONNECT_TIMEOUT),
        "UPDATE_IPSETS_CURL_MAX_TIME": str(UPDATE_IPSETS_CURL_MAX_TIME),
        "UPDATE_IPSETS_CURL_RETRY": str(UPDATE_IPSETS_CURL_RETRY),
        "EXIT_ROUTE_TARGETS": " ".join(target_names),
    }

    for hub in hubs:
        key = exit_route_env_key(hub.name)
        expected[f"EXIT_ROUTE_{key}_PREFIX"] = str(exit_announce_network(hub))

    return expected


def validate_runtime_env_file(
    path: Path, cfg: ConfigData, router_name: str | None = None
) -> None:
    validate_exact_env_values(path, expected_runtime_env_values(cfg, router_name))


def validate_exact_file_set(path: Path, expected: set[str]) -> None:
    if not path.is_dir():
        die(f"missing generated directory: {path}")

    actual = {child.name for child in path.iterdir()}
    missing = sorted(expected - actual)
    if missing:
        die(f"{path}: missing generated entries: {', '.join(missing)}")

    unexpected = sorted(actual - expected)
    if unexpected:
        die(f"{path}: unexpected entries: {', '.join(unexpected)}")

    for name in sorted(expected):
        child = path / name
        if not child.is_file():
            die(f"{path}: expected regular file: {name}")


def validate_ipset_files(cfg: ConfigData) -> None:
    ipset_filenames = {
        REL_DIRECT_STATIC_IPSET.name,
        REL_DIRECT_IPSET.name,
    }

    router_paths: list[Path] = []
    for router_name in cfg.router_names:
        root = router_dir(cfg, router_name)
        validate_exact_file_set(root / REL_IPSETS_ROOT, ipset_filenames)
        router_paths.extend(
            [
                root / REL_DIRECT_STATIC_IPSET,
                root / REL_RUNTIME_ENV,
                root / REL_DIRECT_IPSET,
            ]
        )
        validate_runtime_env_file(root / REL_RUNTIME_ENV, cfg, router_name)

    server_paths: list[Path] = []
    for hub in cfg.exit_hubs:
        server_ipsets = server_path(hub.name, "etc", "ipsets")
        validate_exact_file_set(server_ipsets, ipset_filenames)
        server_paths.extend(
            [
                server_path(hub.name, "etc", "ipsets", "direct-static.txt"),
                server_path(hub.name, "etc", "ipsets", "direct.txt"),
            ]
        )

    for path in router_paths + server_paths:
        if not path.exists():
            die(f"missing generated ipset file: {path}")
        if (
            path.name != RUNTIME_ENV_FILENAME
            and not path.read_text(encoding="utf-8").strip()
        ):
            die(f"empty generated ipset file: {path}")
