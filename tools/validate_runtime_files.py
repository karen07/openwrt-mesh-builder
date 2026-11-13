#!/usr/bin/env python3
from pathlib import Path

from .awg_model import awg_for_infra_direction, peer_endpoint
from .config_exit_model import server_exit_subnets
from .config_model import ConfigData
from .default import (
    DEFAULT_ALLOWED_IPS_TEXT,
    DIRECT_CIDR_OVER_COVERAGE,
    IPIP_SERVER_IFACE,
    NODE_SERVER_IFACE,
    REL_DIRECT_IPSET,
    REL_DIRECT_STATIC_IPSET,
    REL_IPSETS_ROOT,
    RUNTIME_DIRECT_OUT_NAME,
    RUNTIME_DIRECT_STATIC_NAME,
    RUNTIME_IPSETS_DIR,
    RUNTIME_UCI_FILES,
    SERVER_ENV_IPSET_NAME,
    SERVER_ROUTE_PROBE_IP,
    UPDATE_IPSETS_CURL_CONNECT_TIMEOUT,
    UPDATE_IPSETS_CURL_MAX_TIME,
    UPDATE_IPSETS_CURL_RETRY,
    URL_IPINFO_LITE_CSV_GZ,
    URL_IPVERSE_ASN,
)
from .file_ops import read
from .generated_files import exit_server_aliases_for_hub
from .layout import (
    router_dir,
    server_babeld_conf_remote_path,
    server_client_conf_path,
    server_exit_dir,
    server_path,
)
from .link_alias_model import (
    build_exit_client_alias,
    build_exit_exit_alias,
    build_exit_reverse_client_alias,
)
from .link_model import (
    client_iface_name_for_target,
    compute_exit_exit_link_params,
    compute_exit_link_params,
    compute_exit_reverse_link_params,
    compute_mesh_link_params,
    exit_exit_link_key,
    exit_exit_link_pairs,
    exit_in_iface_name,
    exit_link_key,
    exit_out_iface_name,
    exit_reverse_link_key,
    mesh_link_specs_for_router,
)
from .net_model import exit_ipip_endpoint_addr4, exit_node_addr4
from .process import die
from .tunnel_model import (
    exit_hub_is_public,
    ipip_mtu_value,
    router_is_public_mesh_hub,
)
from .validate_awg_helpers import (
    find_block_by_type_and_name,
    require_option,
    validate_awg_conf_options,
)
from .validate_context import validate_optional_mtu
from .validate_keys import parse_tunnel_conf, require_tunnel_sections


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
                key = exit_link_key(hub.name, router_name)
                awg = awg_for_infra_direction(key, hub.name, router_name)
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
                    peer,
                    "PersistentKeepalive",
                    awg.persistent_keepalive,
                    str(conf_path),
                )

        for router_name in cfg.mesh_hubs_by_name:
            client_alias = build_exit_reverse_client_alias(cfg, hub.name, router_name)
            link = compute_exit_reverse_link_params(cfg, hub, router_name)
            key = exit_reverse_link_key(hub.name, router_name)
            awg = awg_for_infra_direction(key, hub.name, router_name)
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
            require_option(
                peer, "PersistentKeepalive", awg.persistent_keepalive, str(conf_path)
            )

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        key = exit_exit_link_key(left_hub.name, right_hub.name)

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
            awg = awg_for_infra_direction(key, local_hub.name, peer_hub.name)
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
            require_option(
                peer, "PersistentKeepalive", awg.persistent_keepalive, str(conf_path)
            )


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
            "ROUTE_PROBE_IP": SERVER_ROUTE_PROBE_IP,
            "AWG_SERVICES": awg_services,
            "BABELD_CONF": server_babeld_conf_remote_path(hub.name),
        }
        validate_exact_env_values(path, expected)
        ipsets_expected = {
            "COUNTRIES": " ".join(cfg.exit_direct.countries),
            "ASNS": " ".join(cfg.exit_direct.asns),
            "DIR": RUNTIME_IPSETS_DIR,
            "STATIC_NAME": RUNTIME_DIRECT_STATIC_NAME,
            "OUT_NAME": RUNTIME_DIRECT_OUT_NAME,
            "IPINFO_URL": URL_IPINFO_LITE_CSV_GZ,
            "IPVERSE_ASN_URL": URL_IPVERSE_ASN,
            "CIDR_OVER_COVERAGE": DIRECT_CIDR_OVER_COVERAGE,
            "CONNECT_TIMEOUT": str(UPDATE_IPSETS_CURL_CONNECT_TIMEOUT),
            "MAX_TIME": str(UPDATE_IPSETS_CURL_MAX_TIME),
            "RETRY": str(UPDATE_IPSETS_CURL_RETRY),
        }
        validate_exact_env_values(
            server_path(hub.name, "etc", "update-ipsets.env"), ipsets_expected
        )


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
                *(root / "files/etc/config" / name for name in RUNTIME_UCI_FILES),
                root / REL_DIRECT_IPSET,
            ]
        )
        from .generate_runtime import build_router_runtime_configs

        for name, content in build_router_runtime_configs(cfg, router_name).items():
            path = root / "files/etc/config" / name
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                die(f"bad generated UCI config: {path}")
        user_path = root / "files/etc/config/exit_route"
        from .generate_runtime import build_exit_route_config

        expected = build_exit_route_config(cfg, router_name)
        if not user_path.is_file() or user_path.read_text(encoding="utf-8") != expected:
            die(f"bad generated exit_route: {user_path}")
        if (root / "files/etc/config/exit_route_base").exists():
            die(f"stale exit_route_base: {root}")

    server_paths: list[Path] = []
    for hub in cfg.exit_hubs:
        server_ipsets = server_exit_dir(hub.name) / RUNTIME_IPSETS_DIR.lstrip("/")
        validate_exact_file_set(server_ipsets, ipset_filenames)
        server_paths.extend(
            [
                server_ipsets / RUNTIME_DIRECT_STATIC_NAME,
                server_ipsets / RUNTIME_DIRECT_OUT_NAME,
            ]
        )

    for path in router_paths + server_paths:
        if not path.exists():
            die(f"missing generated ipset file: {path}")
        if not path.read_text(encoding="utf-8").strip():
            die(f"empty generated ipset file: {path}")
