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
        router_is_public_mesh_hub,
    )
    from .default import OPENVPN_SERVER_CN
    from .validate_context import (
        validate_optional_mtu,
        validate_optional_ipip_mtu,
        vprint,
    )
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
        router_is_public_mesh_hub,
    )
    from default import OPENVPN_SERVER_CN  # type: ignore
    from validate_context import (  # type: ignore
        validate_optional_mtu,
        validate_optional_ipip_mtu,
        vprint,
    )


def validate_encrypted_config_secrets(
    value: object, where: str, config_path: Path
) -> None:
    if isinstance(value, str):
        if "ROUTER_SECRET_V1" in value:
            die(f"{where}: legacy ROUTER_SECRET_V1 marker is not supported")
        if "OWMB_" in value:
            decrypt_owmb_text(value, where, config_path=config_path)
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            validate_encrypted_config_secrets(item, f"{where}[{idx}]", config_path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            validate_encrypted_config_secrets(item, f"{where}.{key}", config_path)
        return


# ============================================================
# UCI / CONF PARSERS
# ============================================================
