#!/usr/bin/env python3
"""Validated per-router DHCP reservations and tagged DHCP options."""

import ipaddress
import re
import sys

sys.dont_write_bytecode = True

from .config_model import DhcpConfig, DhcpHost, DhcpTag, RouterDef
from .config_schema import DHCP_HOST_KEYS, require_known_keys
from .identifiers import require_file_identifier
from .process import die

MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def require_uci_value(value: object, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        die(f"{where} must be a non-empty string of at most 256 characters")
    if any(ord(c) < 32 or ord(c) > 126 or c == "'" for c in value):
        die(f"{where} contains characters unsafe for UCI")
    return value


def load_dhcp_config(
    raw_hosts: object,
    router: RouterDef,
    where: str,
) -> DhcpConfig:
    if not isinstance(raw_hosts, list):
        die(f"{where}.dhcp_hosts must be a list")

    network = ipaddress.IPv4Network(f"{router.lan_prefix}.0/24")
    hosts: list[DhcpHost] = []
    tags: list[DhcpTag] = []
    tag_names: set[str] = set()
    host_names: set[str] = set()
    host_ips: set[str] = set()
    host_macs: set[str] = set()
    for idx, item in enumerate(raw_hosts):
        loc = f"{where}.dhcp_hosts[{idx}]"
        if not isinstance(item, dict):
            die(f"{loc} must be an object")
        require_known_keys(item, loc, DHCP_HOST_KEYS)
        name = item.get("name")
        if not isinstance(name, str) or not name:
            die(f"{loc}.name is required")
        require_file_identifier(name, f"{loc}.name")
        if name.lower() in host_names:
            die(f"{loc}: duplicate host name {name}")
        host_names.add(name.lower())

        ip = item.get("ip")
        if not isinstance(ip, str):
            die(f"{loc}.ip must be a LAN IPv4 address")
        try:
            address = ipaddress.IPv4Address(ip)
        except ipaddress.AddressValueError:
            die(f"{loc}.ip must be a valid IPv4 address: {ip}")
        if (
            str(address) != ip
            or address not in network
            or address
            in (
                network.network_address,
                network.broadcast_address,
                ipaddress.IPv4Address(router.lan_prefix + ".1"),
            )
        ):
            die(f"{loc}.ip must be an available LAN address in {network}: {ip}")
        if ip in host_ips:
            die(f"{loc}: duplicate DHCP IP {ip}")
        host_ips.add(ip)

        raw_mac = item.get("mac")
        if not isinstance(raw_mac, str) or not MAC_RE.fullmatch(raw_mac):
            die(f"{loc}.mac must be a MAC string")
        mac = raw_mac.upper()
        if mac in host_macs:
            die(f"{loc}: duplicate DHCP MAC {mac}")
        host_macs.add(mac)

        host_tags: tuple[str, ...] = ()
        if "dhcp_options" in item:
            raw_options = item["dhcp_options"]
            if not isinstance(raw_options, list) or not raw_options:
                die(f"{loc}.dhcp_options must be a non-empty list")
            options: list[str] = []
            for number, value in enumerate(raw_options):
                option = require_uci_value(value, f"{loc}.dhcp_options[{number}]")
                if not re.fullmatch(r"[0-9]+,.+", option):
                    die(f"{loc}.dhcp_options[{number}] must be CODE,VALUE")
                options.append(option)
            suffix = (
                "dns" if all(o.split(",", 1)[0] == "6" for o in options) else "dhcp"
            )
            tag_name = name.lower() + suffix
            require_file_identifier(tag_name, f"{loc} generated DHCP tag")
            if tag_name in tag_names:
                die(f"{loc}: duplicate generated DHCP tag {tag_name}")
            tag_names.add(tag_name)
            tags.append(DhcpTag(name=tag_name, dhcp_options=tuple(options)))
            host_tags = (tag_name,)

        hosts.append(DhcpHost(name=name, ip=ip, mac=mac, tags=host_tags))

    return DhcpConfig(hosts=tuple(hosts), tags=tuple(tags))
