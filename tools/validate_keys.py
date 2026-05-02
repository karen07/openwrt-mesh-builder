#!/usr/bin/env python3
from pathlib import Path

try:
    from .common import *
    from .wg_keys import derive_public_key
    from .materials import wireguard_private_key_plaintext
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
    from materials import wireguard_private_key_plaintext  # type: ignore
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


def parse_tunnel_conf(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        die(f"missing tunnel config: {path}")

    sections: dict[str, dict[str, str]] = {}
    current: str | None = None

    for lineno, raw in enumerate(read(path).splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            if not current:
                die(f"{path}:{lineno}: empty section name")
            if current in sections:
                die(f"{path}:{lineno}: duplicate [{current}] section")
            sections[current] = {}
            continue

        if "=" in line and current:
            k, v = line.split("=", 1)
            key = k.strip()
            if not key:
                die(f"{path}:{lineno}: empty option name")
            if key in sections[current]:
                die(f"{path}:{lineno}: duplicate option {key!r} in [{current}]")
            sections[current][key] = v.strip()
            continue

        die(f"{path}:{lineno}: cannot parse line: {raw!r}")

    return sections


def require_tunnel_sections(
    conf: dict[str, dict[str, str]], path: Path, expected: set[str]
) -> None:
    actual = set(conf)
    if actual != expected:
        die(f"{path}: bad sections: expected {sorted(expected)}, got {sorted(actual)}")


def public_key_or_die(priv: str, where: str) -> str:
    if not priv:
        die(f"{where}: empty private key")
    try:
        return derive_public_key(wireguard_private_key_plaintext(priv))
    except SystemExit:
        raise
    except Exception as e:
        die(f"{where}: invalid WireGuard/AmneziaWG private key: {e}")


def verify_private_public(priv: str, expected_pub: str, where: str) -> None:
    if not expected_pub:
        die(f"{where}: empty expected public key")
    actual = public_key_or_die(priv, where)
    if actual != expected_pub:
        die(f"key mismatch at {where}: expected public {expected_pub}, got {actual}")


def validate_openvpn_certs(cfg: ConfigData) -> None:
    for router_name, groups in cfg.access.items():
        for group in groups:
            if group.protocol != PROTOCOL_OPENVPN:
                continue

            ca_dir = router_openvpn_ca_dir(cfg, router_name, group.name)
            ca_key = ca_dir / "ca.key"
            ca_pem = ca_dir / "ca.pem"

            if not ca_key.exists():
                die(f"missing OpenVPN CA private key: {ca_key}")
            if not ca_pem.exists():
                die(f"missing OpenVPN CA certificate: {ca_pem}")

            verify_key_matches_cert(ca_key, ca_pem)
            check_cert_cn(
                f"OpenVPN CA {router_name}/{group.name}",
                ca_pem,
                DEFAULT_CA_CN,
                log=vprint,
            )

            server_conf = router_openvpn_server_conf_path(cfg, router_name, group.name)
            server_text = read(server_conf)

            server_ca, server_cert, server_key = openvpn_inline_material(server_text)

            if not server_ca or not server_cert or not server_key:
                die(f"missing inline OpenVPN server material in {server_conf}")

            validate_openvpn_inline_material(
                label=f"OpenVPN server {router_name}/{group.name}",
                ca_pem_text=server_ca,
                cert_pem_text=server_cert,
                key_pem_text=server_key,
                expected_cn=OPENVPN_SERVER_CN,
                log=vprint,
            )

            clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
            for idx, user_name in enumerate(group.users, start=1):
                ovpn_path = clients_dir / f"{user_name}.ovpn"
                text = read(ovpn_path)

                client_ca, client_cert, client_key = openvpn_inline_material(text)

                if not client_ca or not client_cert or not client_key:
                    die(f"missing inline OpenVPN client material in {ovpn_path}")

                validate_openvpn_inline_material(
                    label=f"OpenVPN client {router_name}/{group.name}/{user_name}",
                    ca_pem_text=client_ca,
                    cert_pem_text=client_cert,
                    key_pem_text=client_key,
                    expected_cn=openvpn_client_cn(idx),
                    log=vprint,
                )


# ============================================================
# VALIDATION: KEYS
# ============================================================


def validate_router_keys(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for router_name in cfg.router_names:
        parsed = existing[router_name]

        for block in parsed.values():
            if block.get("type") == "interface":
                opts = block.get("options", {})
                if opts.get("proto") in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
                    priv = opts.get("private_key")
                    if priv:
                        pub = public_key_or_die(
                            str(priv),
                            f"router {router_name} iface {block.get('name')}",
                        )
                        vprint(
                            f"[KEY] router={router_name} iface={block.get('name')} public={pub}"
                        )

        for group in cfg.access.get(router_name, []):
            if group.protocol not in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
                continue

            validate_optional_mtu(
                get_interface_option(parsed, group.name, "mtu"),
                f"access {router_name}/{group.name}",
            )

            for user_name in group.users:
                peer = find_access_peer_block(
                    parsed, group.name, user_name, group.protocol
                )
                if not peer:
                    die(
                        f"missing access peer block for {router_name}/{group.name}/{user_name}"
                    )
                opts = peer.get("options", {})
                pub = opts.get("public_key")
                if not pub:
                    die(
                        f"missing access peer public_key for "
                        f"{router_name}/{group.name}/{user_name}"
                    )

                client_conf = (
                    router_wireguard_clients_dir(cfg, router_name, group.name)
                    / f"{user_name}.conf"
                )
                conf = parse_tunnel_conf(client_conf)
                priv = conf.get("Interface", {}).get("PrivateKey")
                if not priv:
                    die(f"missing WG-like access client PrivateKey in {client_conf}")

                verify_private_public(
                    priv, pub, f"access {router_name}/{group.name}/{user_name}"
                )


def validate_server_tunnel_key_pair(path: Path, label: str) -> str:
    conf = parse_tunnel_conf(path)
    require_tunnel_sections(conf, path, {"Interface", "Peer"})

    iface = conf.get("Interface", {})
    peer = conf.get("Peer", {})

    priv = iface.get("PrivateKey")
    peer_pub = peer.get("PublicKey")
    if not priv or not peer_pub:
        die(f"incomplete server config: {path}")

    public = public_key_or_die(priv, str(path))
    vprint(f"[AWG] {label} local_public={public} peer_public={peer_pub}")
    return public


def validate_server_keys(cfg: ConfigData) -> None:
    for hub in cfg.exit_hubs:
        for alias in exit_server_aliases_for_hub(cfg, hub):
            path = server_client_conf_path(hub.name, alias)
            validate_server_tunnel_key_pair(
                path, f"server={hub.name} client_alias={alias}"
            )


# ============================================================
# VALIDATION: TUNNEL CONF CONSISTENCY
# ============================================================
