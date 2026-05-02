#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

try:
    from .common import *
    from .wg_keys import derive_public_key
    from .package_model import validate_raw_router_package_policy
    from .generated_files import (
        exit_server_aliases_for_hub,
        validate_generated_files_exist,
    )
    from .validate_firewall import validate_firewall
    from .validate_access import validate_access_links, validate_openvpn_uci
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
        validate_current_network_objects,
        validate_link_is_31_pair,
        validate_link_local_matches_ipv4,
        validate_subnet_isolation,
        validate_unique_tunnel_addresses,
    )
    from .validate_ports import (
        validate_exit_server_local_ports,
        validate_router_local_ports,
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
except ImportError:
    from common import *
    from wg_keys import derive_public_key
    from package_model import validate_raw_router_package_policy  # type: ignore
    from generated_files import (  # type: ignore
        exit_server_aliases_for_hub,
        validate_generated_files_exist,
    )
    from validate_firewall import validate_firewall  # type: ignore
    from validate_access import validate_access_links, validate_openvpn_uci  # type: ignore
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
        validate_current_network_objects,
        validate_link_is_31_pair,
        validate_link_local_matches_ipv4,
        validate_subnet_isolation,
        validate_unique_tunnel_addresses,
    )
    from validate_ports import (  # type: ignore
        validate_exit_server_local_ports,
        validate_router_local_ports,
    )
    from validate_uci import parse_uci_file  # type: ignore
    from openvpn_model import (  # type: ignore
        check_cert_cn,
        openvpn_client_cn,
        openvpn_inline_material,
        validate_openvpn_inline_material,
        verify_key_matches_cert,
    )
    from tunnel_model import (
        exit_hub_is_public,
        exit_route_env_key,
        ipip_mtu_value,
        router_is_public_mesh_hub,
    )
    from default import OPENVPN_SERVER_CN


try:
    from .validate_context import set_verbose, vprint
    from .validate_secrets import validate_encrypted_config_secrets
    from .validate_keys import (
        validate_openvpn_certs,
        validate_router_keys,
        validate_server_keys,
    )
    from .validate_runtime_files import (
        validate_exit_server_confs,
        validate_ipset_files,
        validate_router_endpoints,
        validate_runtime_env_file,
        validate_server_env,
    )
    from .validate_tunnel_files import (
        validate_exit_pair_confs,
        validate_mesh_pair_confs,
    )
    from .validate_router_files import (
        validate_babeld,
        validate_router_network_parse_clean,
    )
except ImportError:
    from validate_context import set_verbose, vprint  # type: ignore
    from validate_secrets import validate_encrypted_config_secrets  # type: ignore
    from validate_keys import (  # type: ignore
        validate_openvpn_certs,
        validate_router_keys,
        validate_server_keys,
    )
    from validate_runtime_files import (  # type: ignore
        validate_exit_server_confs,
        validate_ipset_files,
        validate_router_endpoints,
        validate_runtime_env_file,
        validate_server_env,
    )
    from validate_tunnel_files import (  # type: ignore
        validate_exit_pair_confs,
        validate_mesh_pair_confs,
    )
    from validate_router_files import (  # type: ignore
        validate_babeld,
        validate_router_network_parse_clean,
    )


def main(argv: list[str] | None = None) -> None:

    ap = argparse.ArgumentParser(
        description="Validation script for generated mesh/exit/access configs"
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable verbose output",
    )
    args = ap.parse_args(argv)

    set_verbose(args.verbose)

    raw_cfg = load_json_config(Path(args.config))
    validate_config_known_keys(raw_cfg)
    validate_encrypted_config_secrets(raw_cfg, "config", Path(args.config))
    cfg = build_config_data(raw_cfg)
    validate_raw_router_package_policy(raw_cfg, cfg)

    need("wg", "openssl")

    vprint("=== GENERATED FILE VALIDATION ===")
    validate_generated_files_exist(cfg)
    validate_openvpn_uci(cfg)

    existing = load_existing_network_cfgs(cfg)
    validate_router_network_parse_clean(cfg)

    vprint("=== TOPOLOGY VALIDATION ===")
    validate_subnet_isolation(cfg)
    validate_unique_tunnel_addresses(cfg)
    validate_link_local_matches_ipv4(cfg)

    vprint("=== ACCESS CERT VALIDATION ===")
    validate_openvpn_certs(cfg)

    vprint("=== TUNNEL VALIDATION ===")
    validate_router_keys(cfg, existing)
    validate_server_keys(cfg)
    validate_router_endpoints(cfg, existing)
    validate_exit_server_confs(cfg)
    validate_server_env(cfg)
    validate_ipset_files(cfg)
    validate_mesh_pair_confs(cfg, existing)
    validate_exit_pair_confs(cfg, existing)
    validate_access_links(cfg, existing)
    validate_current_network_objects(cfg, existing)

    vprint("=== FIREWALL VALIDATION ===")
    validate_firewall(cfg)

    vprint("=== ROUTING VALIDATION ===")
    validate_babeld(cfg)

    vprint("=== PORT VALIDATION ===")
    validate_router_local_ports(cfg, existing)
    validate_exit_server_local_ports(cfg)

    print("OK: validation finished successfully")


if __name__ == "__main__":
    main()
