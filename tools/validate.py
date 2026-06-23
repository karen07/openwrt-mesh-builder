#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import ipaddress
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from .common import *
    from .default import (
        DEFAULT_ALLOWED_IPS,
        LOCAL_TEMP_ROOT,
        OPENVPN_CLIENT_PROTO,
        OPENVPN_SERVER_CN,
        OPENVPN_SERVER_PROTO,
        ROUTER_REQUIRED_ACCESS_PACKAGES,
        ROUTER_REQUIRED_PACKAGES,
    )
except ImportError:
    from common import *
    from default import (
        DEFAULT_ALLOWED_IPS,
        LOCAL_TEMP_ROOT,
        OPENVPN_CLIENT_PROTO,
        OPENVPN_SERVER_CN,
        OPENVPN_SERVER_PROTO,
        ROUTER_REQUIRED_ACCESS_PACKAGES,
        ROUTER_REQUIRED_PACKAGES,
    )


def validate_optional_mtu(actual: str | None, where: str) -> None:
    if TUNNEL_MTU is None:
        if actual is not None:
            die(f"{where}: unexpected MTU")
        return
    if actual != str(TUNNEL_MTU):
        die(f"{where}: bad MTU")


def ipip_mtu_value() -> int | None:
    if IPIP_DEFAULT_MTU is not None:
        return IPIP_DEFAULT_MTU
    if TUNNEL_MTU is not None:
        return TUNNEL_MTU - 20
    return None


def exit_hub_is_public(hub: ExitHub) -> bool:
    return bool(hub.listen_ip)


def router_is_public_mesh_hub(cfg: ConfigData, router_name: str) -> bool:
    return router_name in cfg.mesh_hubs_by_name


def router_exit_listen_port(cfg: ConfigData, hub: ExitHub, router_name: str) -> int:
    return exit_reverse_listen_port(cfg, hub, router_name)


def exit_reverse_firewall_rule_name(hub_name: str) -> str:
    return f"Allow-Exit-Reverse-{hub_name}"


def validate_optional_ipip_mtu(actual: str | None, where: str) -> None:
    value = ipip_mtu_value()
    if value is None:
        if actual not in (None, ""):
            die(f"{where}: unexpected IPIP MTU")
        return
    if actual != str(value):
        die(f"{where}: bad IPIP MTU: expected {value}, got {actual!r}")


VERBOSE = False


# ============================================================
# BASIC HELPERS
# ============================================================


def vprint(*args, **kwargs) -> None:
    if VERBOSE:
        print(*args, **kwargs)


def validate_encrypted_config_secrets(
    value: object, where: str, config_path: Path
) -> None:
    if isinstance(value, str):
        if "ROUTER_SECRET_V1" in value:
            try:
                from .secrets import decrypt_text as decrypt_secret_text
            except ImportError:
                from secrets import decrypt_text as decrypt_secret_text
            decrypt_secret_text(value, where, config_path=config_path)
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


# ============================================================
# OPENSSL HELPERS
# ============================================================


def openssl_verify_cert(ca_pem: Path, cert_pem: Path) -> None:
    subprocess.run(
        ["openssl", "verify", "-CAfile", str(ca_pem), str(cert_pem)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def openssl_cert_subject_cn(cert_pem: Path) -> str:
    subj = sh(
        [
            "openssl",
            "x509",
            "-in",
            str(cert_pem),
            "-noout",
            "-subject",
            "-nameopt",
            "RFC2253",
        ]
    )
    m = re.search(r"CN=([^,]+)", subj)
    if not m:
        die(f"certificate has no CN: {cert_pem}")
    return m.group(1)


def openssl_pubkey_from_cert(cert_pem: Path) -> str:
    return sh(["openssl", "x509", "-in", str(cert_pem), "-pubkey", "-noout"])


def openssl_pubkey_from_private_key(key_pem: Path) -> str:
    return sh(["openssl", "pkey", "-in", str(key_pem), "-pubout"])


def verify_key_matches_cert(key_pem: Path, cert_pem: Path) -> None:
    k = openssl_pubkey_from_private_key(key_pem)
    c = openssl_pubkey_from_cert(cert_pem)
    if k != c:
        die(f"private key does not match certificate: key={key_pem} cert={cert_pem}")


def public_key_or_die(priv: str, where: str) -> str:
    if not priv:
        die(f"{where}: empty private key")
    try:
        return public_key_from_private(priv)
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


# ============================================================
# REPORTING
# ============================================================


def print_cert_cn(label: str, cert_pem: Path, expected_cn: str) -> None:
    actual = openssl_cert_subject_cn(cert_pem)
    vprint(f"[CERT] {label}: CN={actual} expected={expected_cn}")
    if actual != expected_cn:
        die(f"CN mismatch for {label}: expected {expected_cn}, got {actual}")


# ============================================================
# VALIDATION: CERTS
# ============================================================


def validate_openvpn_inline_material(
    label: str,
    ca_pem_text: str,
    cert_pem_text: str,
    key_pem_text: str,
    expected_cn: str,
) -> None:
    with tempfile.TemporaryDirectory(
        prefix=".validate-cert-",
        dir=LOCAL_TEMP_ROOT,
    ) as td:
        tmp = Path(td)
        ca_pem = tmp / "ca.pem"
        cert_pem = tmp / "cert.pem"
        key_pem = tmp / "key.pem"

        ca_pem.write_text(ca_pem_text, encoding="utf-8")
        cert_pem.write_text(cert_pem_text, encoding="utf-8")
        key_pem.write_text(key_pem_text, encoding="utf-8")

        openssl_verify_cert(ca_pem, cert_pem)
        verify_key_matches_cert(key_pem, cert_pem)
        print_cert_cn(label, cert_pem, expected_cn)
        print_cert_cn(f"{label} CA", ca_pem, DEFAULT_CA_CN)


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
            print_cert_cn(
                f"OpenVPN CA {router_name}/{group.name}", ca_pem, DEFAULT_CA_CN
            )

            server_conf = router_openvpn_server_conf_path(cfg, router_name, group.name)
            server_text = read(server_conf)

            server_ca = extract_inline_block(server_text, "ca")
            server_cert = extract_inline_block(server_text, "cert")
            server_key = extract_inline_block(server_text, "key")

            if not server_ca or not server_cert or not server_key:
                die(f"missing inline OpenVPN server material in {server_conf}")

            validate_openvpn_inline_material(
                label=f"OpenVPN server {router_name}/{group.name}",
                ca_pem_text=server_ca,
                cert_pem_text=server_cert,
                key_pem_text=server_key,
                expected_cn=OPENVPN_SERVER_CN,
            )

            clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
            for idx, user_name in enumerate(group.users, start=1):
                ovpn_path = clients_dir / f"{user_name}.ovpn"
                text = read(ovpn_path)

                client_ca = extract_inline_block(text, "ca")
                client_cert = extract_inline_block(text, "cert")
                client_key = extract_inline_block(text, "key")

                if not client_ca or not client_cert or not client_key:
                    die(f"missing inline OpenVPN client material in {ovpn_path}")

                validate_openvpn_inline_material(
                    label=f"OpenVPN client {router_name}/{group.name}/{user_name}",
                    ca_pem_text=client_ca,
                    cert_pem_text=client_cert,
                    key_pem_text=client_key,
                    expected_cn=openvpn_client_cn(idx),
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


def exit_exit_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return sorted(
        build_exit_exit_alias(cfg, hub.name, peer_name)
        for peer_name in exit_exit_peer_names_for_hub(cfg, hub)
    )


def exit_direct_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    if not exit_hub_is_public(hub):
        return []
    return [build_exit_client_alias(cfg, hub.name, name) for name in cfg.router_names]


def exit_reverse_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return [
        build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
        for mesh_hub in cfg.mesh_hubs
    ]


def exit_server_aliases_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return sorted(
        set(exit_direct_aliases_for_hub(cfg, hub))
        | set(exit_reverse_aliases_for_hub(cfg, hub))
        | set(exit_exit_aliases_for_hub(cfg, hub))
    )


def require_option(opts: dict[str, str], key: str, expected: str, where: str) -> None:
    actual = opts.get(key)
    if actual != expected:
        die(f"{where}: bad {key}: expected {expected!r}, got {actual!r}")


def require_list(
    lists: dict[str, list[str]], key: str, expected: list[str], where: str
) -> None:
    actual = lists.get(key, [])
    if actual != expected:
        die(f"{where}: bad list {key}: expected {expected!r}, got {actual!r}")


def awg_conf_key_map() -> dict[str, str]:
    return {
        "awg_jc": "Jc",
        "awg_jmin": "Jmin",
        "awg_jmax": "Jmax",
        "awg_s1": "S1",
        "awg_s2": "S2",
        "awg_s3": "S3",
        "awg_s4": "S4",
        "awg_h1": "H1",
        "awg_h2": "H2",
        "awg_h3": "H3",
        "awg_h4": "H4",
        "awg_i1": "I1",
        "awg_i2": "I2",
        "awg_i3": "I3",
        "awg_i4": "I4",
        "awg_i5": "I5",
    }


def validate_awg_uci_options(opts: dict[str, str], awg: AwgOptions, where: str) -> None:
    expected = awg_uci_options(awg)
    for key, value in expected.items():
        require_option(opts, key, value, where)

    # If an I* option is empty in config.json, it must not be left stale in UCI.
    for key in ("awg_i1", "awg_i2", "awg_i3", "awg_i4", "awg_i5"):
        if key not in expected and key in opts:
            die(f"{where}: unexpected stale {key}")


def validate_awg_conf_options(
    iface: dict[str, str], awg: AwgOptions, where: str
) -> None:
    expected_uci = awg_uci_options(awg)
    key_map = awg_conf_key_map()
    for uci_key, conf_key in key_map.items():
        expected = expected_uci.get(uci_key)
        actual = iface.get(conf_key)
        if expected is None:
            if actual is not None:
                die(f"{where}: unexpected stale {conf_key}")
        elif actual != expected:
            die(f"{where}: bad {conf_key}: expected {expected!r}, got {actual!r}")


def validate_link_is_31_pair(server_ip: str, client_ip: str, where: str) -> None:
    try:
        server = ipaddress.IPv4Interface(server_ip)
        client = ipaddress.IPv4Interface(client_ip)
    except ValueError as e:
        die(f"{where}: bad IPv4 link address: {e}")

    if (
        server.network.prefixlen != P2P_LINK_PREFIXLEN
        or client.network.prefixlen != P2P_LINK_PREFIXLEN
    ):
        die(
            f"{where}: link addresses must both be /{P2P_LINK_PREFIXLEN}: "
            f"{server_ip} {client_ip}"
        )

    if server.network != client.network:
        die(
            f"{where}: link addresses are not in the same /{P2P_LINK_PREFIXLEN}: "
            f"{server_ip} {client_ip}"
        )

    if int(server.ip) != int(server.network.network_address):
        die(f"{where}: server address must be the first address in {server.network}")
    if int(client.ip) != int(server.ip) + 1:
        die(
            f"{where}: addresses do not form the expected /31 pair: "
            f"{server_ip} {client_ip}"
        )


def require_interface_block(
    parsed: dict[str, dict[str, object]], iface_name: str, where: str
) -> dict[str, object]:
    block = find_block_by_type_and_name(parsed, "interface", iface_name)
    if block is None:
        die(f"{where}: missing interface {iface_name}")
    return block


def require_peer_block(
    parsed: dict[str, dict[str, object]], peer_type: str, where: str
) -> dict[str, object]:
    block = find_block_by_type_and_name(parsed, peer_type)
    if block is None:
        die(f"{where}: missing peer block {peer_type}")
    return block


def public_from_iface(block: dict[str, object], where: str) -> str:
    opts = block.get("options", {})
    priv = opts.get("private_key")
    if not priv:
        die(f"{where}: missing private_key")
    return public_key_or_die(str(priv), where)


def validate_router_awg_interface_common(
    block: dict[str, object], awg: AwgOptions, addresses: list[str], where: str
) -> str:
    opts = block.get("options", {})
    lists = block.get("lists", {})
    require_option(opts, "proto", PROTOCOL_AMNEZIAWG, where)
    require_option(opts, "defaultroute", "0", where)
    validate_optional_mtu(opts.get("mtu"), where)
    validate_awg_uci_options(opts, awg, where)
    require_list(lists, "addresses", addresses, where)
    return public_from_iface(block, where)


def validate_awg_peer_common(
    block: dict[str, object], expected_public_key: str, where: str
) -> None:
    opts = block.get("options", {})
    lists = block.get("lists", {})
    require_option(opts, "public_key", expected_public_key, where)
    require_option(opts, "route_allowed_ips", "1", where)
    require_option(opts, "persistent_keepalive", str(KEEPALIVE), where)
    require_list(lists, "allowed_ips", DEFAULT_ALLOWED_IPS, where)


# ============================================================
# VALIDATION: TUNNEL CONF CONSISTENCY
# ============================================================


def find_block_by_type_and_name(
    parsed: dict[str, dict[str, object]],
    typ: str,
    name: str | None = None,
) -> dict[str, object] | None:
    for block in parsed.values():
        if block.get("type") != typ:
            continue
        if name is not None and block.get("name") != name:
            continue
        return block
    return None


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


def find_firewall_rule_by_name(
    parsed_blocks: list[dict[str, object]], name: str
) -> dict[str, object] | None:
    for block in parsed_blocks:
        if block.get("type") != "rule":
            continue
        options = block.get("options", {})
        if options.get("name") == name:
            return block
    return None


def require_firewall_rule_port(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    port: int,
    proto: str,
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")

    options = block.get("options", {})
    if options.get("src") != FIREWALL_ZONE_WAN:
        die(f"{path}: firewall rule {name}: bad src")
    if options.get("dest_port") != str(port):
        die(f"{path}: firewall rule {name}: bad dest_port")
    if options.get("proto") != proto:
        die(f"{path}: firewall rule {name}: bad proto")
    if options.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {name}: bad target")


def require_firewall_rule_absent(
    parsed_blocks: list[dict[str, object]], path: Path, name: str
) -> None:
    if find_firewall_rule_by_name(parsed_blocks, name) is not None:
        die(f"{path}: stale firewall rule {name}")


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


def exit_route_env_key(name: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_]", "_", name).upper()
    if not key or key[0].isdigit():
        key = f"_{key}"
    return key


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


def add_port(used: dict[int, str], port: int, desc: str, scope: str) -> None:
    if port in used:
        die(f"{scope}: local port collision on {port}: {used[port]} vs {desc}")
    used[port] = desc


def expected_router_uci_listeners(cfg: ConfigData, router_name: str) -> dict[str, int]:
    expected: dict[str, int] = {}

    if router_name in cfg.mesh_hubs_by_name:
        hub = cfg.mesh_hubs_by_name[router_name]
        for _hub_name, target_router in mesh_link_specs_for_hub(cfg, router_name):
            iface = mesh_server_iface_name_for_target(target_router)
            expected[iface] = compute_mesh_link_params(cfg, hub, target_router).port

    if router_is_public_mesh_hub(cfg, router_name):
        for hub in cfg.exit_hubs:
            expected[exit_in_iface_name(hub.name)] = router_exit_listen_port(
                cfg, hub, router_name
            )

    for group in cfg.access.get(router_name, []):
        if group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
            expected[group.name] = group.port

    return expected


def expected_router_host_ports(cfg: ConfigData, router_name: str) -> dict[str, int]:
    expected = dict(expected_router_uci_listeners(cfg, router_name))

    for group in cfg.access.get(router_name, []):
        if group.protocol == PROTOCOL_OPENVPN:
            expected[group.name] = group.port

    return expected


def openvpn_server_port_if_present(
    cfg: ConfigData,
    router_name: str,
    group: AccessGroup,
) -> int | None:
    path = router_openvpn_server_conf_path(cfg, router_name, group.name)
    if not path.exists():
        return None

    for line in read(path).splitlines():
        m = re.fullmatch(r"\s*port\s+(\d+)\s*", line)
        if not m:
            continue
        return int(m.group(1))

    return None


def validate_router_local_ports(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for router_name in cfg.router_names:
        parsed = existing[router_name]
        expected_uci = expected_router_uci_listeners(cfg, router_name)
        expected_host = expected_router_host_ports(cfg, router_name)
        expected_used: dict[int, str] = {}
        actual_used: dict[int, str] = {}

        for name, port in expected_host.items():
            add_port(
                expected_used,
                port,
                f"expected listener:{name}",
                f"router {router_name}",
            )

        for group in cfg.access.get(router_name, []):
            if group.protocol != PROTOCOL_OPENVPN:
                continue
            port = openvpn_server_port_if_present(cfg, router_name, group)
            if port is not None:
                add_port(
                    actual_used,
                    port,
                    f"actual openvpn:{group.name}",
                    f"router {router_name}",
                )

        for block in parsed.values():
            if block.get("type") != "interface":
                continue

            iface = str(block.get("name", ""))
            opts = block.get("options", {})
            lp = opts.get("listen_port")
            if not lp:
                continue

            try:
                port = int(str(lp))
            except ValueError:
                die(f"router {router_name}: bad listen_port on {iface}: {lp!r}")
            if port < PORT_MIN or port > PORT_MAX:
                die(
                    f"router {router_name}: listen_port out of range on {iface}: {port}"
                )

            add_port(
                actual_used, port, f"actual iface:{iface}", f"router {router_name}"
            )

            if iface in expected_uci and expected_uci[iface] != port:
                die(
                    f"router {router_name}: bad listen_port on {iface}: "
                    f"expected {expected_uci[iface]}, got {port}"
                )

        actual_uci_listeners = {
            str(block.get("name", ""))
            for block in parsed.values()
            if block.get("type") == "interface"
            and block.get("options", {}).get("listen_port")
        }
        missing = sorted(set(expected_uci) - actual_uci_listeners)
        if missing:
            die(
                f"router {router_name}: missing expected UCI listeners: {', '.join(missing)}"
            )

        vprint(
            f"[PORTS] router={router_name} ok ({len(actual_used)} unique local ports)"
        )


def validate_exit_server_local_ports(cfg: ConfigData) -> None:
    for hub in cfg.exit_hubs:
        used: dict[int, str] = {}

        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                client_alias = build_exit_client_alias(cfg, hub.name, router_name)
                link = compute_exit_link_params(cfg, hub, router_name)
                add_port(
                    used,
                    link.port,
                    f"wg-server:{client_alias}",
                    f"exit hub server {hub.name}",
                )

        for peer_name in exit_exit_peer_names_for_hub(cfg, hub):
            other = cfg.exit_hubs_by_name[peer_name]
            alias = build_exit_exit_alias(cfg, hub.name, other.name)
            link = compute_exit_exit_link_params(cfg, hub, other)
            port = link.left_port if hub.name == link.left_name else link.right_port
            add_port(
                used,
                port,
                f"exit-exit:{alias}:{other.name}",
                f"exit hub server {hub.name}",
            )

        vprint(f"[PORTS] exit-server={hub.name} ok ({len(used)} unique local ports)")


# ============================================================
# VALIDATION: VIRTUAL DEPLOY INVARIANTS
# ============================================================


def expected_mesh_exit_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return current_mesh_exit_ifaces(cfg, router_name)


def expected_access_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return {group.name for group in cfg.access.get(router_name, [])}


def expected_wireguard_access_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return {
        group.name
        for group in cfg.access.get(router_name, [])
        if group.protocol == PROTOCOL_WIREGUARD
    }


def expected_amneziawg_access_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return {
        group.name
        for group in cfg.access.get(router_name, [])
        if group.protocol == PROTOCOL_AMNEZIAWG
    }


def expected_babel_tunnel_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    names: set[str] = mesh_iface_names_for_router(cfg, router_name)

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            names.add(exit_out_iface_name(hub.name))
        if router_is_public_mesh_hub(cfg, router_name):
            names.add(exit_in_iface_name(hub.name))

    return names


def expected_tunnel_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    # Babel should run only on the real AWG/WG mesh+exit links.
    # Router-side IPIP interfaces are data-path egress tunnels to exits,
    # not Babel neighbour links.
    return expected_babel_tunnel_ifaces(cfg, router_name)


def expected_managed_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return expected_mesh_exit_ifaces(cfg, router_name) | expected_access_ifaces(
        cfg, router_name
    )


def validate_current_network_objects(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for router_name in cfg.router_names:
        expected_ifaces = expected_managed_ifaces(cfg, router_name)
        parsed = existing[router_name]

        for block in parsed.values():
            typ = str(block.get("type", ""))
            name = str(block.get("name", ""))
            opts = block.get("options", {})

            if typ == "interface":
                proto = str(opts.get("proto", ""))
                if (
                    proto in {PROTOCOL_AMNEZIAWG, PROTOCOL_WIREGUARD}
                    and name not in expected_ifaces
                ):
                    die(
                        f"router {router_name}: "
                        f"unexpected managed tunnel interface {name}"
                    )
                continue

            if typ.startswith("amneziawg_"):
                iface = typ.removeprefix("amneziawg_")
                expected = expected_mesh_exit_ifaces(
                    cfg, router_name
                ) | expected_amneziawg_access_ifaces(cfg, router_name)
                if iface not in expected:
                    die(
                        f"router {router_name}: "
                        f"unexpected AmneziaWG peer section {typ}"
                    )

            if typ.startswith("wireguard_"):
                iface = typ.removeprefix("wireguard_")
                if iface not in expected_wireguard_access_ifaces(cfg, router_name):
                    die(
                        f"router {router_name}: "
                        f"unexpected WireGuard peer section {typ}"
                    )


def network4(value: str, where: str) -> ipaddress.IPv4Network:
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as e:
        die(f"{where}: invalid IPv4 network {value!r}: {e}")


def validate_subnet_isolation(cfg: ConfigData) -> None:
    nets: list[tuple[str, ipaddress.IPv4Network]] = []

    for router in cfg.routers:
        nets.append(
            (f"LAN {router.name}", network4(router.lan_ipaddr, f"LAN {router.name}"))
        )

    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        nets.append(
            (
                f"mesh {hub.name}->{target_name}",
                network4(link.srv_ip4, f"mesh {hub.name}->{target_name}"),
            )
        )

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                link = compute_exit_link_params(cfg, hub, router_name)
                nets.append(
                    (
                        f"exit {hub.name}->{router_name}",
                        network4(link.srv_ip4, f"exit {hub.name}->{router_name}"),
                    )
                )

    for hub in cfg.exit_hubs:
        for mesh_hub in cfg.mesh_hubs:
            link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
            label = f"exit-reverse {hub.name}->{mesh_hub.name}"
            nets.append((label, network4(link.srv_ip4, label)))

    for hub in cfg.exit_hubs:
        nets.append((f"exit-node {hub.name}", exit_node_network(hub)))

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        nets.append(
            (
                f"exit-exit {left_hub.name}<->{right_hub.name}",
                network4(
                    link.left_ip4, f"exit-exit {left_hub.name}<->{right_hub.name}"
                ),
            )
        )

    for router_name, groups in cfg.access.items():
        for group in groups:
            nets.append(
                (
                    f"access {router_name}/{group.name}",
                    network4(
                        f"{group.subnet}.0/{ACCESS_SUBNET_CIDR}",
                        f"access {router_name}/{group.name}",
                    ),
                )
            )

    for i, (left_name, left_net) in enumerate(nets):
        for right_name, right_net in nets[i + 1 :]:
            if left_net.overlaps(right_net):
                die(
                    f"subnet overlap: {left_name} {left_net} vs {right_name} {right_net}"
                )

    vprint(f"[SUBNETS] ok ({len(nets)} networks)")


def validate_link_local_matches_ipv4(cfg: ConfigData) -> None:
    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        if link.srv_ll != ipv4_to_link_local(link.srv_ip4):
            die(f"mesh {hub.name}->{target_name}: bad server link-local")
        if link.cli_ll != ipv4_to_link_local(link.cli_ip4):
            die(f"mesh {hub.name}->{target_name}: bad client link-local")

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                link = compute_exit_link_params(cfg, hub, router_name)
                if link.srv_ll != ipv4_to_link_local(link.srv_ip4):
                    die(f"exit {hub.name}->{router_name}: bad server link-local")
                if link.cli_ll != ipv4_to_link_local(link.cli_ip4):
                    die(f"exit {hub.name}->{router_name}: bad client link-local")
        for mesh_hub in cfg.mesh_hubs:
            link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
            if link.srv_ll != ipv4_to_link_local(link.srv_ip4):
                die(f"exit-reverse {hub.name}->{mesh_hub.name}: bad server link-local")
            if link.cli_ll != ipv4_to_link_local(link.cli_ip4):
                die(f"exit-reverse {hub.name}->{mesh_hub.name}: bad client link-local")

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        if link.left_ll != ipv4_to_link_local(link.left_ip4):
            die(f"exit-exit {left_hub.name}<->{right_hub.name}: bad left link-local")
        if link.right_ll != ipv4_to_link_local(link.right_ip4):
            die(f"exit-exit {left_hub.name}<->{right_hub.name}: bad right link-local")


def validate_unique_tunnel_addresses(cfg: ConfigData) -> None:
    used: dict[str, str] = {}

    def add_addr(addr: str, where: str) -> None:
        ip = ipv4_without_prefix(addr)
        if ip in used:
            die(f"duplicate tunnel address {ip}: {used[ip]} vs {where}")
        used[ip] = where

    def add_pair(server_ip: str, client_ip: str, where: str) -> None:
        validate_link_is_31_pair(server_ip, client_ip, where)
        add_addr(server_ip, f"{where} server")
        add_addr(client_ip, f"{where} client")

    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        add_pair(link.srv_ip4, link.cli_ip4, f"mesh {hub.name}->{target_name}")

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                link = compute_exit_link_params(cfg, hub, router_name)
                add_pair(link.srv_ip4, link.cli_ip4, f"exit {hub.name}->{router_name}")
        for mesh_hub in cfg.mesh_hubs:
            link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
            add_pair(
                link.srv_ip4,
                link.cli_ip4,
                f"exit-reverse {hub.name}->{mesh_hub.name}",
            )

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        add_pair(
            link.left_ip4,
            link.right_ip4,
            f"exit-exit {left_hub.name}<->{right_hub.name}",
        )

    vprint(f"[ADDR] tunnel IPv4 ok ({len(used)} addresses)")


def parse_uci_file(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        die(f"missing file: {path}")
    return [
        parsed
        for parsed in (parse_uci_block(block) for block in split_uci_blocks(read(path)))
        if parsed
    ]


def find_firewall_zone_by_name(
    parsed_blocks: list[dict[str, object]], name: str
) -> dict[str, object] | None:
    for block in parsed_blocks:
        if block.get("type") != "zone":
            continue
        if block.get("options", {}).get("name") == name:
            return block
    return None


def require_firewall_zone_networks(
    parsed_blocks: list[dict[str, object]], path: Path, name: str, expected: set[str]
) -> None:
    block = find_firewall_zone_by_name(parsed_blocks, name)
    if not expected:
        if block is not None:
            die(f"{path}: stale firewall zone {name}")
        return
    if block is None:
        die(f"{path}: missing firewall zone {name}")

    actual_list = block.get("lists", {}).get("network", [])
    actual = set(actual_list)
    if len(actual) != len(actual_list):
        die(f"{path}: firewall zone {name}: duplicate network entry")
    if actual != expected:
        die(
            f"{path}: firewall zone {name}: "
            f"expected networks {sorted(expected)}, got {sorted(actual)}"
        )


def require_firewall_zone_policy(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    *,
    input_policy: str,
    output_policy: str,
    forward_policy: str,
    masq: bool = False,
    mtu_fix: bool | None = None,
) -> None:
    block = find_firewall_zone_by_name(parsed_blocks, name)
    if block is None:
        return

    opts = block.get("options", {})
    expected = {
        "input": input_policy,
        "output": output_policy,
        "forward": forward_policy,
    }
    for key, value in expected.items():
        if opts.get(key) != value:
            die(
                f"{path}: firewall zone {name}: bad {key}: "
                f"expected {value!r}, got {opts.get(key)!r}"
            )

    if masq:
        if opts.get("masq") != "1":
            die(f"{path}: firewall zone {name}: missing masq")
    elif "masq" in opts:
        die(f"{path}: firewall zone {name}: stale masq")

    expected_mtu_fix = masq if mtu_fix is None else mtu_fix
    if expected_mtu_fix:
        if opts.get("mtu_fix") != "1":
            die(f"{path}: firewall zone {name}: missing mtu_fix")
    elif "mtu_fix" in opts:
        die(f"{path}: firewall zone {name}: stale mtu_fix")


def require_firewall_mesh_source_rule(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    source_ip: str,
    dest_zone: str | None,
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")
    opts = block.get("options", {})
    lists = block.get("lists", {})
    if opts.get("src") != ZONE_MESH:
        die(f"{path}: firewall rule {name}: bad src")
    if dest_zone is None:
        if "dest" in opts:
            die(f"{path}: firewall rule {name}: unexpected dest")
    elif opts.get("dest") != dest_zone:
        die(f"{path}: firewall rule {name}: bad dest")
    if opts.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {name}: bad target")
    if opts.get("family") != "ipv4":
        die(f"{path}: firewall rule {name}: bad family")
    if opts.get("proto") != "all":
        die(f"{path}: firewall rule {name}: bad proto")
    if lists.get("src_ip", []) != [source_ip]:
        die(f"{path}: firewall rule {name}: bad src_ip")


def require_firewall_dns_transit_access_rule(
    parsed_blocks: list[dict[str, object]], path: Path
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, TRANSIT_ACCESS_DNS_RULE_NAME)
    if block is None:
        die(f"{path}: missing firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}")

    opts = block.get("options", {})
    lists = block.get("lists", {})
    if opts.get("src") != ZONE_TRANSIT_ACCESS:
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad src")
    if opts.get("dest_port") != str(DNS_PORT):
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad dest_port")
    if opts.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad target")
    if lists.get("proto", []) != DNS_PROTOCOLS:
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad proto")


def require_firewall_ssh_from_exit_rule(
    parsed_blocks: list[dict[str, object]], path: Path
) -> None:
    name = "Allow-SSH-From-Exit-To-Router"
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")

    opts = block.get("options", {})
    if opts.get("src") != ZONE_EXIT:
        die(f"{path}: firewall rule {name}: bad src")
    if opts.get("proto") != TRANSPORT_TCP:
        die(f"{path}: firewall rule {name}: bad proto")
    if opts.get("dest_port") != "22":
        die(f"{path}: firewall rule {name}: bad dest_port")
    if opts.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {name}: bad target")


def validate_firewall(cfg: ConfigData) -> None:
    expected_rule_names_by_router: dict[str, set[str]] = {
        name: set() for name in cfg.router_names
    }

    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "firewall")
        parsed = parse_uci_file(path)

        mesh_ifaces = mesh_iface_names_for_router(cfg, router_name)

        exit_ifaces = {
            exit_out_iface_name(hub.name)
            for hub in cfg.exit_hubs
            if exit_hub_is_public(hub)
        }
        if router_is_public_mesh_hub(cfg, router_name):
            exit_ifaces |= {exit_in_iface_name(hub.name) for hub in cfg.exit_hubs}
        exit_ipip_ifaces = {
            router_exit_ipip_iface_name(hub.name)
            for hub in router_exit_order_hubs(cfg, router_name)
        }
        trusted_access = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.policy == ACCESS_POLICY_TRUSTED
        }
        transit_access = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.policy == ACCESS_POLICY_TRANSIT
        }

        require_firewall_zone_networks(parsed, path, ZONE_MESH, mesh_ifaces)
        require_firewall_zone_networks(parsed, path, ZONE_EXIT, exit_ifaces)
        require_firewall_zone_networks(parsed, path, ZONE_EXIT_IPIP, exit_ipip_ifaces)
        require_firewall_zone_networks(
            parsed, path, ZONE_TRUSTED_ACCESS, trusted_access
        )
        require_firewall_zone_networks(
            parsed, path, ZONE_TRANSIT_ACCESS, transit_access
        )

        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_MESH,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )
        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_EXIT,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )
        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_EXIT_IPIP,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )

        # ExitIPIP rule/forwarding entries live in the shared firewall tail.
        # Do not require exact names here: this allows switching between
        # mark-to-main and clear-mark variants without touching validate.py.

        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_TRUSTED_ACCESS,
            input_policy=FIREWALL_TARGET_ACCEPT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )
        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_TRANSIT_ACCESS,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )

        if transit_access:
            expected_rule_names_by_router[router_name].add(TRANSIT_ACCESS_DNS_RULE_NAME)
            require_firewall_dns_transit_access_rule(parsed, path)
        else:
            require_firewall_rule_absent(parsed, path, TRANSIT_ACCESS_DNS_RULE_NAME)

        if config_has_allow_to_router_all(cfg):
            require_firewall_rule_absent(parsed, path, "Allow-SSH-From-Exit-To-Router")
        else:
            expected_rule_names_by_router[router_name].add(
                "Allow-SSH-From-Exit-To-Router"
            )
            require_firewall_ssh_from_exit_rule(parsed, path)

        require_firewall_rule_absent(parsed, path, FIREWALL_RULE_ALLOW_MESH)

        if router_name in cfg.mesh_hubs_by_name:
            hub = cfg.mesh_hubs_by_name[router_name]
            for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
                link = compute_mesh_link_params(cfg, hub, target_name)
                rule_name = mesh_firewall_rule_name(hub.name, target_name)
                expected_rule_names_by_router[router_name].add(rule_name)
                require_firewall_rule_port(
                    parsed, path, rule_name, link.port, TRANSPORT_UDP
                )

            for exit_hub in cfg.exit_hubs:
                rule_name = exit_reverse_firewall_rule_name(exit_hub.name)
                expected_rule_names_by_router[router_name].add(rule_name)
                require_firewall_rule_port(
                    parsed,
                    path,
                    rule_name,
                    router_exit_listen_port(cfg, exit_hub, router_name),
                    TRANSPORT_UDP,
                )

        for group in cfg.access.get(router_name, []):
            rule_name = f"Allow-{group.name}"
            expected_rule_names_by_router[router_name].add(rule_name)
            require_firewall_rule_port(
                parsed,
                path,
                rule_name,
                group.port,
                (
                    TRANSPORT_TCP
                    if group.protocol == PROTOCOL_OPENVPN
                    else TRANSPORT_UDP
                ),
            )

        for allow in cfg.firewall_allows:
            if router_name not in expand_firewall_targets(cfg, allow):
                continue
            rule_name = firewall_allow_rule_name(
                allow.source_name, router_name, allow.kind
            )
            expected_rule_names_by_router[router_name].add(rule_name)
            require_firewall_mesh_source_rule(
                parsed,
                path,
                rule_name,
                allow.source_subnet,
                FIREWALL_ZONE_LAN if allow.kind == FIREWALL_ALLOW_KIND_LAN else None,
            )

        managed_zones = set(MANAGED_FIREWALL_ZONES) | {ZONE_EXIT_IPIP}
        seen_zones: set[str] = set()
        for block in parsed:
            if block.get("type") == "zone":
                zone_name = str(block.get("options", {}).get("name", ""))
                if zone_name in managed_zones:
                    if zone_name in seen_zones:
                        die(f"{path}: duplicate managed firewall zone {zone_name}")
                    seen_zones.add(zone_name)

            if block.get("type") == "rule":
                rule_name = str(block.get("options", {}).get("name", ""))
                looks_managed = (
                    rule_name.startswith("Allow-Mesh-")
                    or rule_name.startswith("Allow-Exit-Reverse-")
                    or (rule_name.startswith("Allow-") and "-To-" in rule_name)
                    or rule_name == TRANSIT_ACCESS_DNS_RULE_NAME
                    or rule_name
                    in {f"Allow-{g.name}" for g in cfg.access.get(router_name, [])}
                )
                if (
                    looks_managed
                    and rule_name not in expected_rule_names_by_router[router_name]
                ):
                    die(f"{path}: stale managed firewall rule {rule_name}")


def validate_babeld(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "babeld")
        parsed = parse_uci_file(path)
        actual: list[str] = []
        for block in parsed:
            if block.get("type") != "interface":
                continue
            ifname = block.get("options", {}).get("ifname")
            if not ifname:
                die(f"{path}: babel interface without ifname")
            if ifname in actual:
                die(f"{path}: duplicate babel interface {ifname}")
            actual.append(str(ifname))

        expected = expected_tunnel_ifaces(cfg, router_name)
        if set(actual) != expected:
            die(
                f"{path}: bad babel tunnel interfaces: "
                f"expected {sorted(expected)}, got {sorted(actual)}"
            )

    for hub in cfg.exit_hubs:
        path = server_babeld_conf_path(hub.name)
        if not path.exists():
            die(f"missing file: {path}")
        actual = set(
            re.findall(r"(?m)^interface\s+(\S+)\s+type\s+tunnel\b", read(path))
        )
        expected = set(exit_server_aliases_for_hub(cfg, hub))
        if actual != expected:
            die(
                f"{path}: bad Exit hub server babel interfaces: "
                f"expected {sorted(expected)}, got {sorted(actual)}"
            )

        lines = read(path).splitlines()

        if "install allow" not in lines:
            die(f"{path}: missing 'install allow'")

        stale_server_babel_lines = {
            "in allow",
            "install deny",
            f"redistribute ip {hub.announce}",
            f"out ip {hub.announce}",
            "out deny",
        }
        for stale in sorted(stale_server_babel_lines):
            if stale in lines:
                die(f"{path}: stale server babel line {stale!r}")

        unexpected_node_redistribute = f"redistribute ip {exit_node_prefix(hub)} allow"
        if unexpected_node_redistribute in lines:
            die(f"{path}: stale server babel line {unexpected_node_redistribute!r}")

        expected_node_redistribute = f"redistribute if {NODE_SERVER_IFACE} allow"
        if expected_node_redistribute not in lines:
            die(f"{path}: missing {expected_node_redistribute!r}")

        expected_redistribute = f"redistribute if {IPIP_SERVER_IFACE} allow"
        if expected_redistribute not in lines:
            die(f"{path}: missing {expected_redistribute!r}")


def router_public_host_for_access_or_die(cfg: ConfigData, router_name: str) -> str:
    endpoint = cfg.access_endpoints.get(router_name)
    if endpoint:
        return endpoint

    die(
        f"access router {router_name}: cannot determine public host; "
        f"add a mesh_hubs entry with listen_ip, or use access_only=true"
    )


def parse_endpoint(value: str, where: str) -> tuple[str, str]:
    if ":" not in value:
        die(f"{where}: endpoint must be host:port")
    host, port = value.rsplit(":", 1)
    if not host or not port:
        die(f"{where}: endpoint must be host:port")
    return host, port


def require_awg_uci_options(
    opts: dict[str, str], awg: AwgOptions | None, where: str
) -> None:
    if awg is None:
        die(f"{where}: missing awg options in config model")

    expected = awg_uci_options(awg)
    for key, value in expected.items():
        require_option(opts, key, value, where)


def require_awg_client_options(
    opts: dict[str, str], awg: AwgOptions | None, where: str
) -> None:
    if awg is None:
        die(f"{where}: missing awg options in config model")

    expected = {
        "Jc": str(awg.jc),
        "Jmin": str(awg.jmin),
        "Jmax": str(awg.jmax),
        "S1": str(awg.s1),
        "S2": str(awg.s2),
        "S3": str(awg.s3),
        "S4": str(awg.s4),
        "H1": awg.h1,
        "H2": awg.h2,
        "H3": awg.h3,
        "H4": awg.h4,
    }
    for key in ("I1", "I2", "I3", "I4", "I5"):
        value = getattr(awg, key.lower())
        if value:
            expected[key] = value

    for key, value in expected.items():
        require_option(opts, key, value, where)


def validate_wireguard_access(
    cfg: ConfigData,
    existing: dict[str, dict[str, dict[str, object]]],
) -> None:
    for router_name, groups in cfg.access.items():
        parsed = existing[router_name]
        public_host = (
            router_public_host_for_access_or_die(cfg, router_name) if groups else ""
        )
        dns_ip = f"{lan_subnet_prefix(cfg, router_name)}.1"

        for group in groups:
            if group.protocol not in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
                continue

            iface = require_interface_block(
                parsed,
                group.name,
                f"access {router_name}/{group.name}",
            )
            opts = iface.get("options", {})
            lists = iface.get("lists", {})
            require_option(
                opts, "proto", group.protocol, f"access {router_name}/{group.name}"
            )
            if group.protocol == PROTOCOL_AMNEZIAWG:
                require_awg_uci_options(
                    opts, group.awg, f"access {router_name}/{group.name}"
                )
            require_option(
                opts,
                "listen_port",
                str(group.port),
                f"access {router_name}/{group.name}",
            )
            require_option(
                opts, "defaultroute", "0", f"access {router_name}/{group.name}"
            )
            validate_optional_mtu(opts.get("mtu"), f"access {router_name}/{group.name}")
            require_list(
                lists,
                "addresses",
                [
                    host_ip_in_prefix(
                        group.subnet, ACCESS_SERVER_HOST, ACCESS_SUBNET_CIDR
                    )
                ],
                f"access {router_name}/{group.name}",
            )
            server_public = public_from_iface(
                iface, f"access {router_name}/{group.name}"
            )

            for idx, user_name in enumerate(group.users):
                client_ip = host_ip_in_prefix(
                    group.subnet,
                    ACCESS_HOST_START + idx,
                    CLIENT_TUNNEL_CIDR,
                )
                peer = find_access_peer_block(
                    parsed, group.name, user_name, group.protocol
                )
                if not peer:
                    die(f"access {router_name}/{group.name}/{user_name}: missing peer")
                peer_opts = peer.get("options", {})
                if not peer_opts.get("public_key"):
                    die(
                        f"access {router_name}/{group.name}/{user_name}: missing peer public_key"
                    )
                require_option(
                    peer_opts,
                    "route_allowed_ips",
                    "1",
                    f"access {router_name}/{group.name}/{user_name}",
                )
                require_option(
                    peer_opts,
                    "persistent_keepalive",
                    str(KEEPALIVE),
                    f"access {router_name}/{group.name}/{user_name}",
                )
                require_list(
                    peer.get("lists", {}),
                    "allowed_ips",
                    [client_ip],
                    f"access {router_name}/{group.name}/{user_name}",
                )

                client_conf = (
                    router_wireguard_clients_dir(cfg, router_name, group.name)
                    / f"{user_name}.conf"
                )
                conf = parse_tunnel_conf(client_conf)
                require_tunnel_sections(conf, client_conf, {"Interface", "Peer"})
                client_iface = conf.get("Interface", {})
                client_peer = conf.get("Peer", {})
                require_option(client_iface, "Address", client_ip, str(client_conf))
                require_option(client_iface, "DNS", dns_ip, str(client_conf))
                validate_optional_mtu(client_iface.get("MTU"), str(client_conf))
                if group.protocol == PROTOCOL_AMNEZIAWG:
                    require_awg_client_options(
                        client_iface, group.awg, str(client_conf)
                    )
                require_option(
                    client_peer, "PublicKey", server_public, str(client_conf)
                )
                require_option(
                    client_peer,
                    "AllowedIPs",
                    DEFAULT_ALLOWED_IPS_TEXT,
                    str(client_conf),
                )
                require_option(
                    client_peer, "PersistentKeepalive", str(KEEPALIVE), str(client_conf)
                )
                host, port = parse_endpoint(
                    client_peer.get("Endpoint", ""), str(client_conf)
                )
                if host != public_host or port != str(group.port):
                    die(
                        f"{client_conf}: bad Endpoint: "
                        f"expected {public_host}:{group.port}, got {host}:{port}"
                    )


def require_openvpn_line(text: str, pattern: str, where: str) -> None:
    if not re.search(pattern, text, flags=re.M):
        die(f"{where}: missing expected OpenVPN line matching {pattern!r}")


def require_openvpn_option_line(
    text: str, option: str, value: object, where: str
) -> None:
    require_openvpn_line(
        text,
        rf"^{re.escape(option)}\s+{re.escape(str(value))}\s*$",
        where,
    )


def validate_openvpn_access(cfg: ConfigData) -> None:
    for router_name, groups in cfg.access.items():
        public_host = (
            router_public_host_for_access_or_die(cfg, router_name) if groups else ""
        )
        dns_ip = f"{lan_subnet_prefix(cfg, router_name)}.1"

        for group in groups:
            if group.protocol != PROTOCOL_OPENVPN:
                continue

            server_conf = router_openvpn_server_conf_path(cfg, router_name, group.name)
            text = read(server_conf)
            require_openvpn_option_line(text, "port", group.port, str(server_conf))
            require_openvpn_option_line(
                text, "proto", OPENVPN_SERVER_PROTO, str(server_conf)
            )
            require_openvpn_option_line(text, "dev", group.name, str(server_conf))
            require_openvpn_line(
                text,
                rf"^server\s+{re.escape(group.subnet)}\.0\s+255\.255\.255\.0\s*$",
                str(server_conf),
            )
            require_openvpn_line(
                text,
                rf"^push\s+\"dhcp-option DNS {re.escape(dns_ip)}\"\s*$",
                str(server_conf),
            )

            clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
            for user_name in group.users:
                client_conf = clients_dir / f"{user_name}.ovpn"
                client_text = read(client_conf)
                require_openvpn_option_line(
                    client_text, "proto", OPENVPN_CLIENT_PROTO, str(client_conf)
                )
                require_openvpn_line(
                    client_text,
                    rf"^remote\s+{re.escape(public_host)}\s+"
                    rf"{re.escape(str(group.port))}\s*$",
                    str(client_conf),
                )


def validate_openvpn_uci(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        groups = [
            g for g in cfg.access.get(router_name, []) if g.protocol == PROTOCOL_OPENVPN
        ]

        path = router_path(cfg, router_name, "openvpn_uci")

        if not groups:
            if path.exists():
                die(f"{path}: unexpected OpenVPN UCI file without OpenVPN access")
            continue

        if not path.exists():
            die(f"missing generated OpenVPN UCI file: {path}")

        parsed = parse_uci_file(path)
        actual: dict[str, dict[str, object]] = {}

        for block in parsed:
            typ = str(block.get("type", ""))
            name = str(block.get("name", ""))

            if typ != PROTOCOL_OPENVPN:
                die(f"{path}: unexpected UCI section type {typ!r}")
            if name in actual:
                die(f"{path}: duplicate OpenVPN section {name!r}")

            actual[name] = block

        expected_names = {g.name for g in groups}

        missing = expected_names - set(actual)
        if missing:
            die(f"{path}: missing OpenVPN sections: {', '.join(sorted(missing))}")

        stale = set(actual) - expected_names
        if stale:
            die(f"{path}: stale OpenVPN sections: {', '.join(sorted(stale))}")

        for group in groups:
            block = actual[group.name]
            opts = block.get("options", {})
            lists = block.get("lists", {})
            where = f"{path}:{group.name}"

            require_option(opts, "enabled", "1", where)
            require_option(
                opts,
                "config",
                f"/etc/openvpn/{group.name}/server.ovpn",
                where,
            )
            require_option(opts, "cd", f"/etc/openvpn/{group.name}", where)

            extra_opts = set(opts) - {"enabled", "config", "cd"}
            if extra_opts:
                die(f"{where}: unexpected options: {', '.join(sorted(extra_opts))}")
            if lists:
                die(f"{where}: unexpected list options")


def validate_access_links(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    validate_wireguard_access(cfg, existing)
    validate_openvpn_access(cfg)


def validate_router_network_parse_clean(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "network")
        seen_interfaces: set[str] = set()
        seen_amnezia_peers: set[str] = set()
        wg_peer_descriptions: dict[str, set[str]] = {}

        for block_text in split_uci_blocks(read(path)):
            parsed = parse_uci_block(block_text)
            if not parsed:
                continue

            typ = str(parsed.get("type", ""))
            name = str(parsed.get("name", ""))
            opts = parsed.get("options", {})

            if typ == "interface":
                if name in seen_interfaces:
                    die(f"{path}: duplicate interface section {name}")
                seen_interfaces.add(name)

            if typ.startswith("amneziawg_"):
                iface = typ.removeprefix("amneziawg_")
                if iface in expected_amneziawg_access_ifaces(cfg, router_name):
                    desc = str(opts.get("description", ""))
                    if not desc:
                        die(
                            f"{path}: AmneziaWG access peer section {typ} without description"
                        )
                    seen = wg_peer_descriptions.setdefault(typ, set())
                    if desc in seen:
                        die(
                            f"{path}: duplicate AmneziaWG access peer description {typ}/{desc}"
                        )
                    seen.add(desc)
                else:
                    if typ in seen_amnezia_peers:
                        die(f"{path}: duplicate AmneziaWG peer section {typ}")
                    seen_amnezia_peers.add(typ)

            if typ.startswith("wireguard_"):
                desc = str(opts.get("description", ""))
                if not desc:
                    die(f"{path}: WireGuard peer section {typ} without description")
                seen = wg_peer_descriptions.setdefault(typ, set())
                if desc in seen:
                    die(f"{path}: duplicate WireGuard peer description {typ}/{desc}")
                seen.add(desc)


def validate_generated_files_exist(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        for kind in ("network", "firewall", "babeld", "bootstrap"):
            path = router_path(cfg, router_name, kind)
            if not path.exists():
                die(f"missing generated file: {path}")

        expected_wg_ifaces = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}
        }
        wg_root = router_wireguard_root(cfg, router_name)
        if wg_root.exists():
            actual_wg_ifaces = {p.name for p in wg_root.iterdir() if p.is_dir()}
            stale = actual_wg_ifaces - expected_wg_ifaces
            if stale:
                die(
                    f"{wg_root}: stale WireGuard access dirs: {', '.join(sorted(stale))}"
                )

        expected_ovpn_ifaces = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.protocol == PROTOCOL_OPENVPN
        }
        ovpn_root = router_openvpn_root(cfg, router_name)
        if ovpn_root.exists():
            actual_ovpn_ifaces = {p.name for p in ovpn_root.iterdir() if p.is_dir()}
            stale = actual_ovpn_ifaces - expected_ovpn_ifaces
            if stale:
                die(
                    f"{ovpn_root}: stale OpenVPN access dirs: {', '.join(sorted(stale))}"
                )

        for group in cfg.access.get(router_name, []):
            if group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
                clients_dir = router_wireguard_clients_dir(cfg, router_name, group.name)
                expected_files = {f"{user}.conf" for user in group.users}
                if not clients_dir.exists():
                    die(f"missing generated WG-like clients dir: {clients_dir}")
                actual_files = {p.name for p in clients_dir.iterdir() if p.is_file()}
                stale = actual_files - expected_files
                if stale:
                    die(
                        f"{clients_dir}: stale WG-like client files: {', '.join(sorted(stale))}"
                    )
                for filename in expected_files:
                    path = clients_dir / filename
                    if not path.exists():
                        die(f"missing generated WG-like client config: {path}")

            elif group.protocol == PROTOCOL_OPENVPN:
                for path in (
                    router_openvpn_ca_dir(cfg, router_name, group.name) / "ca.pem",
                    router_openvpn_server_conf_path(cfg, router_name, group.name),
                ):
                    if not path.exists():
                        die(f"missing generated OpenVPN file: {path}")

                clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
                expected_files = {f"{user}.ovpn" for user in group.users}
                if not clients_dir.exists():
                    die(f"missing generated OpenVPN clients dir: {clients_dir}")
                actual_files = {p.name for p in clients_dir.iterdir() if p.is_file()}
                stale = actual_files - expected_files
                if stale:
                    die(
                        f"{clients_dir}: stale OpenVPN client files: {', '.join(sorted(stale))}"
                    )
                for filename in expected_files:
                    path = clients_dir / filename
                    if not path.exists():
                        die(f"missing generated OpenVPN client config: {path}")

    for hub in cfg.exit_hubs:
        server_files_root = server_exit_dir(hub.name) / "files"
        if server_files_root.exists():
            die(
                f"{server_files_root}: unexpected server overlay dir; "
                f"use {server_exit_dir(hub.name) / 'etc'} and "
                f"{server_exit_dir(hub.name) / 'root'}"
            )

        for path in (
            server_babeld_conf_path(hub.name),
            server_path(hub.name, "etc", "awg-server.env"),
            server_path(hub.name, "etc", "ipsets", "direct-static.txt"),
            server_path(hub.name, "etc", "ipsets", "direct.txt"),
            server_path(
                hub.name, "etc", "systemd", "system", AWG_SERVER_NETWORK_SERVICE_NAME
            ),
            server_path(hub.name, "root", ".ssh", "authorized_keys"),
        ):
            if not path.exists():
                die(f"missing generated Exit hub server file: {path}")

        server_dir = server_amneziawg_dir(hub.name)
        expected_files = {
            f"{alias}.conf" for alias in exit_server_aliases_for_hub(cfg, hub)
        }
        if not server_dir.exists():
            die(f"missing generated Exit hub server config dir: {server_dir}")
        actual_files = {p.name for p in server_dir.iterdir() if p.is_file()}
        stale = actual_files - expected_files
        if stale:
            die(
                f"{server_dir}: stale Exit hub server client configs: {', '.join(sorted(stale))}"
            )
        for filename in expected_files:
            path = server_dir / filename
            if not path.exists():
                die(f"missing generated Exit hub client server config: {path}")


def dedupe_packages(packages: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for package in packages:
        if package in seen:
            continue
        result.append(package)
        seen.add(package)

    return result


def validate_raw_package_list(
    value: object, where: str, *, router_override: bool
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        die(f"{where} must be a list of strings")

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item:
            die(f"{where} must be a list of non-empty strings")
        if item in seen:
            die(f"{where}: duplicate package entry: {item}")
        seen.add(item)

        if router_override:
            if len(item) < 2 or item[0] not in "+-":
                die(f"{where} entry must start with + or -: {item}")
            if not item[1:]:
                die(f"{where} has empty package entry: {item}")
        elif item[0] in "+-":
            die(f"{where} entries must not start with + or -: {item}")

        out.append(item)

    return out


def required_router_packages(cfg: ConfigData, router_name: str) -> list[str]:
    packages = list(ROUTER_REQUIRED_PACKAGES)

    for group in cfg.access.get(router_name, []):
        packages.extend(ROUTER_REQUIRED_ACCESS_PACKAGES[group.protocol])

    return dedupe_packages(packages)


def validate_router_packages(raw_cfg: dict[str, object], cfg: ConfigData) -> None:
    global_packages = validate_raw_package_list(
        raw_cfg.get(CONFIG_KEY_PACKAGES),
        "config.packages",
        router_override=False,
    )

    raw_routers = raw_cfg.get(CONFIG_KEY_ROUTERS, [])
    if not isinstance(raw_routers, list):
        die("config key 'routers' must be a list")

    for raw_router in raw_routers:
        if not isinstance(raw_router, dict):
            die("each router entry must be an object")
        router_name = raw_router.get(CONFIG_KEY_NAME)
        if not isinstance(router_name, str) or not router_name:
            die("router name must be a non-empty string")

        required = required_router_packages(cfg, router_name)
        required_set = set(required)
        result = dedupe_packages(required + global_packages)
        present = set(result)

        overrides = validate_raw_package_list(
            raw_router.get(CONFIG_KEY_PACKAGES),
            f"routers[{router_name}].packages",
            router_override=True,
        )

        for entry in overrides:
            op = entry[0]
            package = entry[1:]

            if op == "+":
                if package not in present:
                    result.append(package)
                    present.add(package)
                continue

            if package in required_set:
                die(
                    f"routers[{router_name}].packages tries to remove required "
                    f"managed package: {package}"
                )

            if package not in present:
                die(
                    f"routers[{router_name}].packages tries to remove package "
                    f"that is not currently installed: {package}"
                )

            result = [p for p in result if p != package]
            present.remove(package)

        missing = sorted(required_set - present)
        if missing:
            die(
                f"router {router_name}: missing required managed package(s): "
                + ", ".join(missing)
            )


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    global VERBOSE

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
    args = ap.parse_args()

    VERBOSE = args.verbose

    raw_cfg = load_json_config(Path(args.config))
    validate_config_known_keys(raw_cfg)
    validate_encrypted_config_secrets(raw_cfg, "config", Path(args.config))
    cfg = build_config_data(raw_cfg)
    validate_router_packages(raw_cfg, cfg)

    need("openssl")

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
