#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .access_model import router_public_host_for_access
    from .default import OPENVPN_CLIENT_PROTO, OPENVPN_SERVER_PROTO
    from .network_config import find_access_peer_block
    from .validate_awg_helpers import (
        public_from_iface,
        require_interface_block,
        require_list,
        require_option,
    )
    from .validate_context import validate_optional_mtu
    from .validate_keys import parse_tunnel_conf, require_tunnel_sections
    from .validate_uci import parse_uci_file
except ImportError:
    from common import *  # type: ignore
    from access_model import router_public_host_for_access  # type: ignore
    from default import OPENVPN_CLIENT_PROTO, OPENVPN_SERVER_PROTO  # type: ignore
    from network_config import find_access_peer_block  # type: ignore
    from validate_awg_helpers import (  # type: ignore
        public_from_iface,
        require_interface_block,
        require_list,
        require_option,
    )
    from validate_context import validate_optional_mtu  # type: ignore
    from validate_keys import parse_tunnel_conf, require_tunnel_sections  # type: ignore
    from validate_uci import parse_uci_file  # type: ignore


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
        public_host = router_public_host_for_access(cfg, router_name) if groups else ""
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
        public_host = router_public_host_for_access(cfg, router_name) if groups else ""
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
