#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .process import die, need
    from .config_io import load_json_config
    from .wg_keys import derive_public_key, generate_private_key
    from .secrets import decrypt_text as decrypt_owmb_text
    from .secrets import decrypt_value as decrypt_owmb_value
    from .secrets import encrypt_material_value
except ImportError:
    import importlib.util

    from process import die, need
    from config_io import load_json_config  # type: ignore
    from wg_keys import derive_public_key, generate_private_key

    _secrets_path = Path(__file__).with_name("secrets.py")
    _secrets_spec = importlib.util.spec_from_file_location(
        "owmb_local_secrets", _secrets_path
    )
    if _secrets_spec is None or _secrets_spec.loader is None:
        raise ImportError(f"cannot load {_secrets_path}")
    _secrets_module = importlib.util.module_from_spec(_secrets_spec)
    _secrets_spec.loader.exec_module(_secrets_module)
    decrypt_owmb_text = _secrets_module.decrypt_text
    decrypt_owmb_value = _secrets_module.decrypt_value
    encrypt_material_value = _secrets_module.encrypt_material_value


try:
    from .file_ops import (
        cp_tree,
        encrypted_owmb_state_is_current,
        has_any_owmb_marker,
        has_encrypted_owmb_marker,
        has_plain_owmb_marker,
        read,
        rm,
        write,
    )
except ImportError:
    from file_ops import (  # type: ignore
        cp_tree,
        encrypted_owmb_state_is_current,
        has_any_owmb_marker,
        has_encrypted_owmb_marker,
        has_plain_owmb_marker,
        read,
        rm,
        write,
    )

# ============================================================
# CONSTANTS
# ============================================================

try:
    from .default import *
except ImportError:
    from default import *  # type: ignore

try:
    from .layout import (
        router_dir,
        router_path,
        router_openvpn_root,
        router_openvpn_iface_dir,
        router_openvpn_ca_dir,
        router_openvpn_server_conf_path,
        router_openvpn_clients_dir,
        router_wireguard_root,
        router_wireguard_iface_dir,
        router_wireguard_clients_dir,
        server_dir_name,
        server_exit_dir,
        server_path,
        server_amneziawg_dir,
        server_client_conf_path,
        server_babeld_slug,
        server_babeld_conf_basename,
        server_babeld_conf_path,
        server_babeld_conf_remote_path,
    )
    from .uci import (
        normalize_uci,
        parse_uci_block,
        render_uci_block,
        split_uci_blocks,
    )
except ImportError:
    from layout import (  # type: ignore
        router_dir,
        router_path,
        router_openvpn_root,
        router_openvpn_iface_dir,
        router_openvpn_ca_dir,
        router_openvpn_server_conf_path,
        router_openvpn_clients_dir,
        router_wireguard_root,
        router_wireguard_iface_dir,
        router_wireguard_clients_dir,
        server_dir_name,
        server_exit_dir,
        server_path,
        server_amneziawg_dir,
        server_client_conf_path,
        server_babeld_slug,
        server_babeld_conf_basename,
        server_babeld_conf_path,
        server_babeld_conf_remote_path,
    )
    from uci import (  # type: ignore
        normalize_uci,
        parse_uci_block,
        render_uci_block,
        split_uci_blocks,
    )

try:
    from .openvpn_model import (
        extract_inline_block,
        generate_ed25519_cert_signed_by_ca,
        local_ca_material,
        openvpn_client_cn,
    )
except ImportError:
    from openvpn_model import (  # type: ignore
        extract_inline_block,
        generate_ed25519_cert_signed_by_ca,
        local_ca_material,
        openvpn_client_cn,
    )

try:
    from .identifiers import (
        CANONICAL_IPV4_RE,
        require_arch_path_segment,
        require_ascii_identifier,
        require_device_profile_arch,
        require_device_profile_board,
        require_exit_hub_name,
        require_file_identifier,
        require_file_path_segment,
        require_generated_linux_iface_name,
        require_linux_iface_name,
        require_package_identifier,
    )
except ImportError:
    from identifiers import (  # type: ignore
        CANONICAL_IPV4_RE,
        require_arch_path_segment,
        require_ascii_identifier,
        require_device_profile_arch,
        require_device_profile_board,
        require_exit_hub_name,
        require_file_identifier,
        require_file_path_segment,
        require_generated_linux_iface_name,
        require_linux_iface_name,
        require_package_identifier,
    )


MARKER = FIREWALL_MARKER


try:
    from .config_model import (
        AccessGroup,
        AccessPeerState,
        AwgOptions,
        ConfigData,
        DeviceProfile,
        ExitDirectConfig,
        ExitExitLinkParams,
        ExitHub,
        FirewallAllow,
        KeyMaterial,
        LinkParams,
        MeshHub,
        MeshLinkState,
        PortRange,
        RouterDef,
        RouterExitState,
        WifiConfig,
    )
except ImportError:
    from config_model import (  # type: ignore
        AccessGroup,
        AccessPeerState,
        AwgOptions,
        ConfigData,
        DeviceProfile,
        ExitDirectConfig,
        ExitExitLinkParams,
        ExitHub,
        FirewallAllow,
        KeyMaterial,
        LinkParams,
        MeshHub,
        MeshLinkState,
        PortRange,
        RouterDef,
        RouterExitState,
        WifiConfig,
    )


try:
    from .stable_model import (
        random_free_slots,
        ring_link_pairs,
        stable_hash_u32,
        stable_port_avoiding_for,
        stable_port_for,
        stable_seed_u64,
        stable_unique_values,
        stable_unique_values_avoiding,
    )
    from .net_model import (
        canonical_ipv4,
        config_network_item,
        exit_announce_network,
        exit_announce_target_ip,
        exit_dummy_addr4,
        exit_ipip_endpoint_addr4,
        exit_ipip_endpoint_ip,
        exit_node_addr4,
        exit_node_network,
        exit_node_prefix,
        generated_exit_announce_network,
        generated_exit_node_ip,
        generated_exit_node_network,
        host_ip_in_prefix,
        ipv4_to_link_local,
        ipv4_without_prefix,
        normalize_ipv4_subnet_24_prefix,
        normalize_listen_ip,
        normalize_optional_exit_ip,
        parse_ipv4,
        require_usable_unicast_ipv4_address,
        stable_generated_network_for_key,
        validate_config_networks_do_not_overlap,
    )
    from .link_alias_model import (
        anonymized_link_alias,
        build_exit_base_alias,
        build_exit_client_alias,
        build_exit_exit_alias,
        build_exit_exit_base_alias,
        build_exit_reverse_base_alias,
        build_exit_reverse_client_alias,
        build_mesh_client_alias,
    )
    from .link_model import (
        client_iface_name_for_target,
        compute_exit_exit_link_params,
        compute_exit_link_params,
        compute_exit_reverse_link_params,
        compute_mesh_link_params,
        exit_exit_link_key,
        exit_exit_link_keys,
        exit_exit_link_keys_for_hub,
        exit_exit_link_pair_for_hubs,
        exit_exit_link_pairs,
        exit_exit_pair_names,
        exit_exit_peer_names_for_hub,
        exit_in_iface_name,
        exit_link_key,
        exit_link_keys,
        exit_out_iface_name,
        exit_reverse_link_key,
        exit_reverse_link_keys,
        exit_reverse_listen_port,
        infra_link_keys,
        infra_link_network_from_pair_index,
        link_network_addresses,
        mesh_iface_names_for_router,
        mesh_link_key,
        mesh_link_keys,
        mesh_link_specs,
        mesh_link_specs_for_hub,
        mesh_link_specs_for_router,
        mesh_server_iface_name_for_target,
        public_exit_hub_names,
        stable_exit_exit_link_network_for,
        stable_exit_reverse_link_network_for,
        stable_infra_link_network_for,
        stable_infra_link_pair_indices,
    )
except ImportError:
    from stable_model import (  # type: ignore
        random_free_slots,
        ring_link_pairs,
        stable_hash_u32,
        stable_port_avoiding_for,
        stable_port_for,
        stable_seed_u64,
        stable_unique_values,
        stable_unique_values_avoiding,
    )
    from net_model import (  # type: ignore
        canonical_ipv4,
        config_network_item,
        exit_announce_network,
        exit_announce_target_ip,
        exit_dummy_addr4,
        exit_ipip_endpoint_addr4,
        exit_ipip_endpoint_ip,
        exit_node_addr4,
        exit_node_network,
        exit_node_prefix,
        generated_exit_announce_network,
        generated_exit_node_ip,
        generated_exit_node_network,
        host_ip_in_prefix,
        ipv4_to_link_local,
        ipv4_without_prefix,
        normalize_ipv4_subnet_24_prefix,
        normalize_listen_ip,
        normalize_optional_exit_ip,
        parse_ipv4,
        require_usable_unicast_ipv4_address,
        stable_generated_network_for_key,
        validate_config_networks_do_not_overlap,
    )
    from link_alias_model import (  # type: ignore
        anonymized_link_alias,
        build_exit_base_alias,
        build_exit_client_alias,
        build_exit_exit_alias,
        build_exit_exit_base_alias,
        build_exit_reverse_base_alias,
        build_exit_reverse_client_alias,
        build_mesh_client_alias,
    )
    from link_model import (  # type: ignore
        client_iface_name_for_target,
        compute_exit_exit_link_params,
        compute_exit_link_params,
        compute_exit_reverse_link_params,
        compute_mesh_link_params,
        exit_exit_link_key,
        exit_exit_link_keys,
        exit_exit_link_keys_for_hub,
        exit_exit_link_pair_for_hubs,
        exit_exit_link_pairs,
        exit_exit_pair_names,
        exit_exit_peer_names_for_hub,
        exit_in_iface_name,
        exit_link_key,
        exit_link_keys,
        exit_out_iface_name,
        exit_reverse_link_key,
        exit_reverse_link_keys,
        exit_reverse_listen_port,
        infra_link_keys,
        infra_link_network_from_pair_index,
        link_network_addresses,
        mesh_iface_names_for_router,
        mesh_link_key,
        mesh_link_keys,
        mesh_link_specs,
        mesh_link_specs_for_hub,
        mesh_link_specs_for_router,
        mesh_server_iface_name_for_target,
        public_exit_hub_names,
        stable_exit_exit_link_network_for,
        stable_exit_reverse_link_network_for,
        stable_infra_link_network_for,
        stable_infra_link_pair_indices,
    )


try:
    from .package_model import (
        dedupe_package_names,
        normalize_config_package_list,
        validate_config_package_list,
        managed_router_packages,
        required_managed_router_packages,
        validate_router_package_policy,
    )
except ImportError:
    from package_model import (  # type: ignore
        dedupe_package_names,
        normalize_config_package_list,
        validate_config_package_list,
        managed_router_packages,
        required_managed_router_packages,
        validate_router_package_policy,
    )

try:
    from .awg_model import (
        AWG_KEYS,
        awg_conf_lines,
        awg_for_infra_link,
        awg_uci_options,
        infra_awg_port_range,
        load_awg_options,
        parse_awg_h_range,
        parse_port_range_value,
        peer_endpoint,
        ranges_overlap,
        stable_awg_h_ranges,
        stable_awg_runtime_params,
        validate_awg_auto_ranges,
        validate_awg_h_range_strings,
        validate_awg_h_ranges,
        validate_awg_options,
        validate_awg_runtime_ranges,
    )
except ImportError:
    from awg_model import (  # type: ignore
        AWG_KEYS,
        awg_conf_lines,
        awg_for_infra_link,
        awg_uci_options,
        infra_awg_port_range,
        load_awg_options,
        parse_awg_h_range,
        parse_port_range_value,
        peer_endpoint,
        ranges_overlap,
        stable_awg_h_ranges,
        stable_awg_runtime_params,
        validate_awg_auto_ranges,
        validate_awg_h_range_strings,
        validate_awg_h_ranges,
        validate_awg_options,
        validate_awg_runtime_ranges,
    )

try:
    from .config_builder import *
except ImportError:
    from config_builder import *  # type: ignore


try:
    from .network_config import *
except ImportError:
    from network_config import *  # type: ignore


try:
    from .materials import (
        gen_private_key,
        material_file_for_tool,
        material_plaintext,
        parse_existing_tunnel_conf,
        public_key_from_private,
        stored_key_material,
        write_material_file,
    )
except ImportError:
    from materials import (  # type: ignore
        gen_private_key,
        material_file_for_tool,
        material_plaintext,
        parse_existing_tunnel_conf,
        public_key_from_private,
        stored_key_material,
        write_material_file,
    )


def is_under(relpath: Path, parent: Path) -> bool:
    try:
        relpath.relative_to(parent)
        return True
    except ValueError:
        return False
