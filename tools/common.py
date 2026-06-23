#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import base64
import ipaddress
import json
import os
import random
import re
import shutil
import hashlib
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# ============================================================
# CONSTANTS
# ============================================================

try:
    from .default import (
        ACCESS_HOST_START,
        LOCAL_TEMP_ROOT,
        MIN_OPENWRT_VERSION,
        MIN_OPENWRT_VERSION_TEXT,
        ANON_LINK_ALIAS_HEX_LEN,
        ACCESS_SERVER_HOST,
        ACCESS_SUBNET_CIDR,
        CLIENT_TUNNEL_CIDR,
        ACCESS_POLICY_TRANSIT,
        ACCESS_POLICY_TRUSTED,
        AWG_H_COUNT,
        AWG_H_GAP,
        AWG_H_MAX,
        AWG_H_MIN,
        AWG_H_SPAN_MAX,
        AWG_H_SPAN_MIN,
        AWG_INFRA_AUTO_JC_MAX,
        AWG_INFRA_AUTO_JC_MIN,
        AWG_INFRA_AUTO_JUNK_SIZE_MAX,
        AWG_INFRA_AUTO_JUNK_SIZE_MIN,
        AWG_INFRA_AUTO_S1_MAX,
        AWG_INFRA_AUTO_S1_MIN,
        AWG_INFRA_AUTO_S2_MAX,
        AWG_INFRA_AUTO_S2_MIN,
        AWG_INFRA_AUTO_S3_MAX,
        AWG_INFRA_AUTO_S3_MIN,
        AWG_INFRA_AUTO_S4_MAX,
        AWG_INFRA_AUTO_S4_MIN,
        AWG_INFRA_I1,
        AWG_INFRA_I2,
        AWG_INFRA_I3,
        AWG_INFRA_I4,
        AWG_INFRA_I5,
        AWG_JC_MAX,
        AWG_JC_MIN,
        AWG_JUNK_SIZE_MAX,
        AWG_JUNK_SIZE_MIN,
        AWG_S1_MAX,
        AWG_S1_MIN,
        AWG_S2_MAX,
        AWG_S2_MIN,
        AWG_S3_MAX,
        AWG_S3_MIN,
        AWG_S4_MAX,
        AWG_S4_MIN,
        AWG_SERVER_NETWORK_SERVICE_NAME,
        BABELD_HELLO_INTERVAL,
        BABELD_LAN_IFACE,
        BABELD_LOG_FILE,
        SERVER_BABELD_CONF_PREFIX,
        SERVER_BABELD_CONF_SUFFIX,
        BABELD_SPLIT_HORIZON,
        BABELD_TUNNEL_TYPE,
        BABELD_UBUS_BINDINGS,
        BABELD_UPDATE_INTERVAL,
        CONFIG_PATH,
        CONFIG_KEY_ACCESS,
        CONFIG_KEY_ACCESS_ONLY,
        CONFIG_KEY_ALLOW_TO_LAN,
        CONFIG_KEY_ALLOW_TO_ROUTER,
        CONFIG_KEY_ARCH,
        CONFIG_KEY_AWG,
        CONFIG_KEY_BOARD,
        CONFIG_KEY_DEVICE_PROFILE,
        CONFIG_KEY_DEVICE_PROFILES,
        CONFIG_KEY_EXIT_HUBS,
        CONFIG_KEY_EXIT_ORDER,
        CONFIG_KEY_EXIT_IP,
        CONFIG_KEY_KEY,
        CONFIG_KEY_BLOCKED_MACS,
        CONFIG_KEY_LISTEN_IP,
        CONFIG_KEY_MAIN_ROUTER,
        CONFIG_KEY_MESH_HUBS,
        CONFIG_KEY_NAME,
        CONFIG_KEY_OPENWRT_VERSION,
        CONFIG_KEY_PACKAGES,
        CONFIG_KEY_POLICY,
        CONFIG_KEY_PORT,
        CONFIG_KEY_PROTOCOL,
        CONFIG_KEY_ROUTERS,
        CONFIG_KEY_SSID,
        CONFIG_KEY_SSH_KEY_DIR,
        CONFIG_KEY_SECRET_KEY,
        CONFIG_KEY_SUBNET,
        CONFIG_KEY_USERS,
        CONFIG_KEY_WIFI_2G,
        CONFIG_KEY_WIFI_5G,
        DEFAULT_ALLOWED_IPS,
        DEFAULT_ALLOWED_IPS_TEXT,
        DEFAULT_CA_CN,
        DEFAULT_CERT_DAYS,
        DNS_PORT,
        DNS_PROTOCOLS,
        TRANSPORT_TCP,
        TRANSPORT_UDP,
        IPIP_SERVER_IFACE,
        NODE_SERVER_IFACE,
        IPIP_DEFAULT_MTU,
        EXIT_ANNOUNCE_PREFIXLEN,
        EXIT_ANNOUNCE_SUPERNET4,
        EXIT_NODE_PREFIXLEN,
        EXIT_NODE_SUPERNET4,
        CHECK_DOH_DOMAIN,
        CHECK_DOH_INTERVAL,
        CHECK_DOH_PROVIDER_DOMAINS,
        CHECK_DOH_RESOLV,
        CHECK_DOH_RESOLV_WAIT_MAX,
        EXIT_DIRECT_ASNS,
        EXIT_DIRECT_COUNTRIES,
        EXIT_DIRECT_STATIC_IPSETS,
        EXIT_ROUTE_INTERVAL,
        EXIT_ROUTE_TABLE,
        FIREWALL_MARKER,
        FIREWALL_RULE_ALLOW_MESH,
        FIREWALL_TARGET_ALL,
        FIREWALL_TARGET_ACCEPT,
        FIREWALL_TARGET_REJECT,
        FIREWALL_ZONE_LAN,
        FIREWALL_ZONE_WAN,
        INFRA_AWG_PORT_RANGE,
        INFRA_LINK_POOL,
        LOCAL_DIRECT_IPSETS,
        IPV4_LINK_LOCAL_PREFIXLEN,
        IPV4_OCTET_COUNT,
        IPV4_OCTET_MAX,
        IPV4_OCTET_MIN,
        KEEPALIVE,
        MANAGED_FIREWALL_ZONES,
        OPENVPN_CLIENT_PROTO,
        OPENVPN_DATA_CIPHERS,
        OPENVPN_DEV_TYPE,
        OPENVPN_GROUP,
        OPENVPN_KEEPALIVE,
        OPENVPN_SERVER_CN,
        OPENVPN_SERVER_PROTO,
        OPENVPN_TOPOLOGY,
        OPENVPN_USER,
        OPENVPN_VERB,
        P2P_LINK_HOST_STRIDE,
        P2P_LINK_PREFIXLEN,
        PORT_MAX,
        PORT_MIN,
        PROTOCOL_AMNEZIAWG,
        PROTOCOL_OPENVPN,
        PROTOCOL_WIREGUARD,
        REL,
        REL_RUNTIME_ENV,
        REL_DIRECT_IPSET,
        REL_IPSETS_ROOT,
        REL_DIRECT_STATIC_IPSET,
        REL_DROPBEAR_AUTHORIZED_KEYS,
        STABLE_HASH_U32_DIGEST_SIZE,
        STABLE_SEED_U64_DIGEST_SIZE,
        ROUTER_HOSTNAME_PREFIX,
        ROUTER_SSH_PREFIX,
        ROUTER_REQUIRED_ACCESS_PACKAGES,
        ROUTER_REQUIRED_PACKAGES,
        ROUTERS_ROOT,
        RUNTIME_DIRECT_OUT_NAME,
        RUNTIME_DIRECT_STATIC_NAME,
        RUNTIME_ENV_FILENAME,
        RUNTIME_ENV_REMOTE_PATH,
        RUNTIME_IPSETS_DIR,
        SERVER_ENV_IPSET_NAME,
        SERVER_ROOT,
        SERVER_TEMPLATE_DIR,
        SERVER_TEMPLATE_NAME,
        SHELL_SECRET_WRAP_COL,
        TRANSIT_ACCESS_DNS_RULE_NAME,
        TUNNEL_MTU,
        UPDATE_IPSETS_CURL_CONNECT_TIMEOUT,
        UPDATE_IPSETS_CURL_MAX_TIME,
        UPDATE_IPSETS_CURL_RETRY,
        URL_IPVERSE_ASN,
        URL_IPVERSE_RIR,
        WIFI_CELL_DENSITY,
        WIFI_COUNTRY,
        WIFI_ENCRYPTION,
        WIFI_RADIO_BY_KEY,
        ZONE_EXIT,
        ZONE_EXIT_IPIP,
        ZONE_MESH,
        ZONE_TRANSIT_ACCESS,
        ZONE_TRUSTED_ACCESS,
    )
except ImportError:
    from default import (
        ACCESS_HOST_START,
        LOCAL_TEMP_ROOT,
        MIN_OPENWRT_VERSION,
        MIN_OPENWRT_VERSION_TEXT,
        ANON_LINK_ALIAS_HEX_LEN,
        ACCESS_SERVER_HOST,
        ACCESS_SUBNET_CIDR,
        CLIENT_TUNNEL_CIDR,
        ACCESS_POLICY_TRANSIT,
        ACCESS_POLICY_TRUSTED,
        AWG_H_COUNT,
        AWG_H_GAP,
        AWG_H_MAX,
        AWG_H_MIN,
        AWG_H_SPAN_MAX,
        AWG_H_SPAN_MIN,
        AWG_INFRA_AUTO_JC_MAX,
        AWG_INFRA_AUTO_JC_MIN,
        AWG_INFRA_AUTO_JUNK_SIZE_MAX,
        AWG_INFRA_AUTO_JUNK_SIZE_MIN,
        AWG_INFRA_AUTO_S1_MAX,
        AWG_INFRA_AUTO_S1_MIN,
        AWG_INFRA_AUTO_S2_MAX,
        AWG_INFRA_AUTO_S2_MIN,
        AWG_INFRA_AUTO_S3_MAX,
        AWG_INFRA_AUTO_S3_MIN,
        AWG_INFRA_AUTO_S4_MAX,
        AWG_INFRA_AUTO_S4_MIN,
        AWG_INFRA_I1,
        AWG_INFRA_I2,
        AWG_INFRA_I3,
        AWG_INFRA_I4,
        AWG_INFRA_I5,
        AWG_JC_MAX,
        AWG_JC_MIN,
        AWG_JUNK_SIZE_MAX,
        AWG_JUNK_SIZE_MIN,
        AWG_S1_MAX,
        AWG_S1_MIN,
        AWG_S2_MAX,
        AWG_S2_MIN,
        AWG_S3_MAX,
        AWG_S3_MIN,
        AWG_S4_MAX,
        AWG_S4_MIN,
        AWG_SERVER_NETWORK_SERVICE_NAME,
        BABELD_HELLO_INTERVAL,
        BABELD_LAN_IFACE,
        BABELD_LOG_FILE,
        SERVER_BABELD_CONF_PREFIX,
        SERVER_BABELD_CONF_SUFFIX,
        BABELD_SPLIT_HORIZON,
        BABELD_TUNNEL_TYPE,
        BABELD_UBUS_BINDINGS,
        BABELD_UPDATE_INTERVAL,
        CONFIG_PATH,
        CONFIG_KEY_ACCESS,
        CONFIG_KEY_ACCESS_ONLY,
        CONFIG_KEY_ALLOW_TO_LAN,
        CONFIG_KEY_ALLOW_TO_ROUTER,
        CONFIG_KEY_ARCH,
        CONFIG_KEY_AWG,
        CONFIG_KEY_BOARD,
        CONFIG_KEY_DEVICE_PROFILE,
        CONFIG_KEY_DEVICE_PROFILES,
        CONFIG_KEY_EXIT_HUBS,
        CONFIG_KEY_EXIT_ORDER,
        CONFIG_KEY_EXIT_IP,
        CONFIG_KEY_KEY,
        CONFIG_KEY_BLOCKED_MACS,
        CONFIG_KEY_LISTEN_IP,
        CONFIG_KEY_MAIN_ROUTER,
        CONFIG_KEY_MESH_HUBS,
        CONFIG_KEY_NAME,
        CONFIG_KEY_OPENWRT_VERSION,
        CONFIG_KEY_PACKAGES,
        CONFIG_KEY_POLICY,
        CONFIG_KEY_PORT,
        CONFIG_KEY_PROTOCOL,
        CONFIG_KEY_ROUTERS,
        CONFIG_KEY_SSID,
        CONFIG_KEY_SSH_KEY_DIR,
        CONFIG_KEY_SECRET_KEY,
        CONFIG_KEY_SUBNET,
        CONFIG_KEY_USERS,
        CONFIG_KEY_WIFI_2G,
        CONFIG_KEY_WIFI_5G,
        DEFAULT_ALLOWED_IPS,
        DEFAULT_ALLOWED_IPS_TEXT,
        DEFAULT_CA_CN,
        DEFAULT_CERT_DAYS,
        DNS_PORT,
        DNS_PROTOCOLS,
        TRANSPORT_TCP,
        TRANSPORT_UDP,
        IPIP_SERVER_IFACE,
        NODE_SERVER_IFACE,
        IPIP_DEFAULT_MTU,
        EXIT_ANNOUNCE_PREFIXLEN,
        EXIT_ANNOUNCE_SUPERNET4,
        EXIT_NODE_PREFIXLEN,
        EXIT_NODE_SUPERNET4,
        CHECK_DOH_DOMAIN,
        CHECK_DOH_INTERVAL,
        CHECK_DOH_PROVIDER_DOMAINS,
        CHECK_DOH_RESOLV,
        CHECK_DOH_RESOLV_WAIT_MAX,
        EXIT_DIRECT_ASNS,
        EXIT_DIRECT_COUNTRIES,
        EXIT_DIRECT_STATIC_IPSETS,
        EXIT_ROUTE_INTERVAL,
        EXIT_ROUTE_TABLE,
        FIREWALL_MARKER,
        FIREWALL_RULE_ALLOW_MESH,
        FIREWALL_TARGET_ALL,
        FIREWALL_TARGET_ACCEPT,
        FIREWALL_TARGET_REJECT,
        FIREWALL_ZONE_LAN,
        FIREWALL_ZONE_WAN,
        INFRA_AWG_PORT_RANGE,
        INFRA_LINK_POOL,
        LOCAL_DIRECT_IPSETS,
        IPV4_LINK_LOCAL_PREFIXLEN,
        IPV4_OCTET_COUNT,
        IPV4_OCTET_MAX,
        IPV4_OCTET_MIN,
        KEEPALIVE,
        MANAGED_FIREWALL_ZONES,
        OPENVPN_CLIENT_PROTO,
        OPENVPN_DATA_CIPHERS,
        OPENVPN_DEV_TYPE,
        OPENVPN_GROUP,
        OPENVPN_KEEPALIVE,
        OPENVPN_SERVER_CN,
        OPENVPN_SERVER_PROTO,
        OPENVPN_TOPOLOGY,
        OPENVPN_USER,
        OPENVPN_VERB,
        P2P_LINK_HOST_STRIDE,
        P2P_LINK_PREFIXLEN,
        PORT_MAX,
        PORT_MIN,
        PROTOCOL_AMNEZIAWG,
        PROTOCOL_OPENVPN,
        PROTOCOL_WIREGUARD,
        REL,
        REL_RUNTIME_ENV,
        REL_DIRECT_IPSET,
        REL_IPSETS_ROOT,
        REL_DIRECT_STATIC_IPSET,
        REL_DROPBEAR_AUTHORIZED_KEYS,
        STABLE_HASH_U32_DIGEST_SIZE,
        STABLE_SEED_U64_DIGEST_SIZE,
        ROUTER_HOSTNAME_PREFIX,
        ROUTER_SSH_PREFIX,
        ROUTER_REQUIRED_ACCESS_PACKAGES,
        ROUTER_REQUIRED_PACKAGES,
        ROUTERS_ROOT,
        RUNTIME_DIRECT_OUT_NAME,
        RUNTIME_DIRECT_STATIC_NAME,
        RUNTIME_ENV_FILENAME,
        RUNTIME_ENV_REMOTE_PATH,
        RUNTIME_IPSETS_DIR,
        SERVER_ENV_IPSET_NAME,
        SERVER_ROOT,
        SERVER_TEMPLATE_DIR,
        SERVER_TEMPLATE_NAME,
        SHELL_SECRET_WRAP_COL,
        TRANSIT_ACCESS_DNS_RULE_NAME,
        TUNNEL_MTU,
        UPDATE_IPSETS_CURL_CONNECT_TIMEOUT,
        UPDATE_IPSETS_CURL_MAX_TIME,
        UPDATE_IPSETS_CURL_RETRY,
        URL_IPVERSE_ASN,
        URL_IPVERSE_RIR,
        WIFI_CELL_DENSITY,
        WIFI_COUNTRY,
        WIFI_ENCRYPTION,
        WIFI_RADIO_BY_KEY,
        ZONE_EXIT,
        ZONE_EXIT_IPIP,
        ZONE_MESH,
        ZONE_TRANSIT_ACCESS,
        ZONE_TRUSTED_ACCESS,
    )

PRIVATE_KEY_RE = re.compile(r"(?m)^\s*PrivateKey\s*=\s*(\S+)\s*$")
MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
CONFIG_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")
EXIT_HUB_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FILE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PACKAGE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
CANONICAL_IPV4_RE = re.compile(r"^(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}$")
LINUX_IFACE_NAME_MAX_BYTES = 15
EXIT_HUB_NAME_MAX_BYTES = 8
FILE_IDENTIFIER_MAX_BYTES = 64
PACKAGE_IDENTIFIER_MAX_BYTES = 128
ARCH_IDENTIFIER_MAX_BYTES = 64


def require_ascii_identifier(
    value: str,
    where: str,
    *,
    pattern: re.Pattern[str],
    allowed: str,
    max_bytes: int,
) -> None:
    if not pattern.fullmatch(value):
        die(f"{where} must contain only {allowed}: {value}")
    byte_len = len(value.encode("ascii"))
    if byte_len > max_bytes:
        die(f"{where} is too long: {value} is {byte_len} bytes, max {max_bytes}")


def require_linux_iface_name(value: str, where: str) -> None:
    # Linux IFNAMSIZ is 16 bytes including the trailing NUL, so the
    # visible interface name is limited to 15 ASCII bytes.
    require_ascii_identifier(
        value,
        where,
        pattern=CONFIG_IDENTIFIER_RE,
        allowed="ASCII letters, digits and underscore",
        max_bytes=LINUX_IFACE_NAME_MAX_BYTES,
    )


def require_generated_linux_iface_name(value: str, where: str) -> None:
    # Generated names may contain fixed OpenWrt/Linux prefixes such as
    # "ipip-".  User-controlled fragments are validated separately; here we
    # only enforce the Linux visible interface-name byte limit and reject
    # the characters Linux definitely cannot accept in interface names.
    byte_len = len(value.encode("ascii"))
    if byte_len > LINUX_IFACE_NAME_MAX_BYTES:
        die(
            f"{where} is too long: {value} is {byte_len} bytes, "
            f"max {LINUX_IFACE_NAME_MAX_BYTES}"
        )
    if any(ch in value for ch in ("/", ":")) or any(ch.isspace() for ch in value):
        die(
            f"{where} contains characters that are not valid in Linux interface names: {value}"
        )


def require_exit_hub_name(value: str, where: str) -> None:
    # The generated OpenWrt IPIP section is f"ip{value}". OpenWrt then
    # creates a Linux device named f"ipip-ip{value}", so the visible
    # exit name itself may consume at most 8 ASCII bytes.  Keep this
    # uppercase-only because exit_route_env_key() uppercases names for env
    # variables, where lowercase names would otherwise collide/change.
    require_ascii_identifier(
        value,
        where,
        pattern=EXIT_HUB_IDENTIFIER_RE,
        allowed="uppercase ASCII letters, digits and underscore, starting with a letter",
        max_bytes=EXIT_HUB_NAME_MAX_BYTES,
    )


def require_file_identifier(value: str, where: str) -> None:
    require_ascii_identifier(
        value,
        where,
        pattern=FILE_IDENTIFIER_RE,
        allowed="ASCII letters, digits, underscore, dot and dash",
        max_bytes=FILE_IDENTIFIER_MAX_BYTES,
    )


def require_file_path_segment(value: str, where: str) -> None:
    require_file_identifier(value, where)
    if value in (".", ".."):
        die(f"{where} must not be '.' or '..'")


def require_package_identifier(value: str, where: str) -> None:
    require_ascii_identifier(
        value,
        where,
        pattern=PACKAGE_IDENTIFIER_RE,
        allowed=(
            "ASCII letters, digits, underscore, dot, plus and dash, "
            "starting with a letter, digit or underscore"
        ),
        max_bytes=PACKAGE_IDENTIFIER_MAX_BYTES,
    )


def require_device_profile_board(value: object, where: str) -> None:
    if not isinstance(value, str) or not value:
        die(f"{where} must be like 'target/subtarget'")

    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        die(f"{where} must be like 'target/subtarget'")

    target, subtarget = parts
    require_file_path_segment(target, f"{where} target")
    require_file_path_segment(subtarget, f"{where} subtarget")


def require_arch_path_segment(value: str, where: str) -> None:
    require_ascii_identifier(
        value,
        where,
        pattern=PACKAGE_IDENTIFIER_RE,
        allowed=(
            "ASCII letters, digits, underscore, dot, plus and dash, "
            "starting with a letter, digit or underscore"
        ),
        max_bytes=ARCH_IDENTIFIER_MAX_BYTES,
    )
    if value in (".", ".."):
        die(f"{where} must not be '.' or '..'")


def require_device_profile_arch(value: object, where: str) -> None:
    if not isinstance(value, str) or not value:
        die(f"{where} must be a non-empty string")
    require_arch_path_segment(value, where)


FORCED_CA_ONCE: set[str] = set()

MARKER = FIREWALL_MARKER


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    board: str
    arch: str
    target: str
    subtarget: str


@dataclass(frozen=True)
class RouterDef:
    name: str
    subnet: str
    device_profile: str
    package_overrides: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        return self.name.lower()

    @property
    def path(self) -> Path:
        return ROUTERS_ROOT / self.slug

    @property
    def ssh_host(self) -> str:
        return f"{ROUTER_SSH_PREFIX}{self.slug}"

    @property
    def lan_prefix(self) -> str:
        return self.subnet.rsplit(".", 1)[0]

    @property
    def lan_ipaddr(self) -> str:
        return f"{self.lan_prefix}.1/24"

    @property
    def hostname(self) -> str:
        return f"{ROUTER_HOSTNAME_PREFIX}{self.name}"


@dataclass(frozen=True)
class AwgOptions:
    jc: int
    jmin: int
    jmax: int
    s1: int
    s2: int
    s3: int
    s4: int
    h1: str
    h2: str
    h3: str
    h4: str
    i1: str = ""
    i2: str = ""
    i3: str = ""
    i4: str = ""
    i5: str = ""


@dataclass(frozen=True)
class PortRange:
    start: int
    end: int

    @property
    def span(self) -> int:
        return self.end - self.start + 1

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass(frozen=True)
class MeshHub:
    name: str
    listen_ip: str
    port_range: PortRange


@dataclass(frozen=True)
class ExitHub:
    name: str
    node_ip: str
    listen_ip: str
    exit_ip: str
    announce: str
    port_range: PortRange


@dataclass(frozen=True)
class ExitDirectConfig:
    subnets: list[str]
    countries: list[str]
    asns: list[str]


@dataclass(frozen=True)
class AccessGroup:
    router_name: str
    name: str
    protocol: str
    policy: str
    subnet: str
    port: int
    users: list[str]
    awg: AwgOptions | None = None


@dataclass(frozen=True)
class FirewallAllow:
    source_name: str
    source_router: str
    source_subnet: str
    targets: list[str]
    kind: str


@dataclass(frozen=True)
class LinkParams:
    srv_ip4: str
    cli_ip4: str
    srv_ll: str
    cli_ll: str
    port: int


@dataclass(frozen=True)
class ExitExitLinkParams:
    left_name: str
    right_name: str
    left_ip4: str
    right_ip4: str
    left_ll: str
    right_ll: str
    left_port: int
    right_port: int


@dataclass(frozen=True)
class KeyMaterial:
    client_private: str
    client_public: str
    server_private: str
    server_public: str


@dataclass
class RouterExitState:
    router_name: str
    client_alias: str
    hub: ExitHub
    link: LinkParams
    keys: KeyMaterial
    awg: AwgOptions


@dataclass
class MeshLinkState:
    hub: MeshHub
    target_router: str
    client_alias: str
    server_iface_name: str
    client_iface_name: str
    server_peer_section_name: str
    client_peer_section_name: str
    link: LinkParams
    keys: KeyMaterial
    awg: AwgOptions


@dataclass
class AccessPeerState:
    router_name: str
    iface: str
    user_name: str
    client_ip4: str
    server_ip4: str
    subnet: str
    port: int
    protocol: str
    awg: AwgOptions | None
    client_private: str
    client_public: str
    server_private: str
    server_public: str


@dataclass(frozen=True)
class WifiConfig:
    ssid: str
    key: str
    blocked_macs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigData:
    routers: list[RouterDef]
    router_by_name: dict[str, RouterDef]
    router_names: list[str]
    openwrt_version: str
    main_router: str
    packages: list[str]
    device_profiles: dict[str, DeviceProfile]
    mesh_hubs: list[MeshHub]
    mesh_hubs_by_name: dict[str, MeshHub]
    access_endpoints: dict[str, str]
    exit_hubs: list[ExitHub]
    exit_hubs_by_name: dict[str, ExitHub]
    exit_order: list[str]
    exit_order_by_router: dict[str, list[str]]
    exit_direct: ExitDirectConfig
    access: dict[str, list[AccessGroup]]
    firewall_allows: list[FirewallAllow]
    wifi: dict[str, dict[str, WifiConfig]]


def dedupe_package_names(packages: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for package in packages:
        if package in seen:
            continue
        result.append(package)
        seen.add(package)

    return result


def required_managed_router_packages(
    access_groups: list[AccessGroup],
) -> list[str]:
    packages = list(ROUTER_REQUIRED_PACKAGES)

    for group in access_groups:
        packages.extend(ROUTER_REQUIRED_ACCESS_PACKAGES[group.protocol])

    return dedupe_package_names(packages)


def validate_router_package_policy(
    routers: list[RouterDef],
    global_packages: list[str],
    access: dict[str, list[AccessGroup]],
) -> None:
    for router in routers:
        required = required_managed_router_packages(access.get(router.name, []))
        required_set = set(required)
        result = dedupe_package_names(required + global_packages)
        present = set(result)

        for entry in router.package_overrides:
            op = entry[0]
            package = entry[1:]

            if op == "+":
                if package not in present:
                    result.append(package)
                    present.add(package)
                continue

            if package in required_set:
                die(
                    f"routers[{router.name}].packages tries to remove required "
                    f"managed package: {package}"
                )

            if package not in present:
                die(
                    f"routers[{router.name}].packages tries to remove package "
                    f"that is not currently installed: {package}"
                )

            result = [item for item in result if item != package]
            present.remove(package)

        missing = sorted(required_set - present)
        if missing:
            die(
                f"router {router.name}: missing required managed package(s): "
                + ", ".join(missing)
            )


CONFIG_KEYS = {
    CONFIG_KEY_SSH_KEY_DIR,
    CONFIG_KEY_SECRET_KEY,
    CONFIG_KEY_OPENWRT_VERSION,
    CONFIG_KEY_PACKAGES,
    CONFIG_KEY_DEVICE_PROFILES,
    CONFIG_KEY_MAIN_ROUTER,
    CONFIG_KEY_ROUTERS,
    CONFIG_KEY_MESH_HUBS,
    CONFIG_KEY_EXIT_HUBS,
    CONFIG_KEY_EXIT_ORDER,
    CONFIG_KEY_ACCESS,
}

DEVICE_PROFILE_KEYS = {
    CONFIG_KEY_BOARD,
    CONFIG_KEY_ARCH,
}

ROUTER_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_DEVICE_PROFILE,
    CONFIG_KEY_SUBNET,
    CONFIG_KEY_PACKAGES,
    CONFIG_KEY_EXIT_ORDER,
    CONFIG_KEY_ALLOW_TO_LAN,
    CONFIG_KEY_ALLOW_TO_ROUTER,
    CONFIG_KEY_WIFI_2G,
    CONFIG_KEY_WIFI_5G,
}

WIFI_KEYS = {
    CONFIG_KEY_SSID,
    CONFIG_KEY_KEY,
    CONFIG_KEY_BLOCKED_MACS,
}

WIFI_CONFIG_KEYS = (CONFIG_KEY_WIFI_2G, CONFIG_KEY_WIFI_5G)

MESH_HUB_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_LISTEN_IP,
    CONFIG_KEY_ACCESS_ONLY,
}

EXIT_HUB_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_LISTEN_IP,
    CONFIG_KEY_EXIT_IP,
}


AWG_KEYS = {
    "jc",
    "jmin",
    "jmax",
    "s1",
    "s2",
    "s3",
    "s4",
    "h1",
    "h2",
    "h3",
    "h4",
    "i1",
    "i2",
    "i3",
    "i4",
    "i5",
}

ACCESS_PROTOCOLS = {PROTOCOL_WIREGUARD, PROTOCOL_OPENVPN, PROTOCOL_AMNEZIAWG}
ACCESS_POLICIES = {ACCESS_POLICY_TRUSTED, ACCESS_POLICY_TRANSIT}

FIREWALL_ALLOW_KIND_ROUTER = "router"
FIREWALL_ALLOW_KIND_LAN = "lan"

ACCESS_KEYS = {
    CONFIG_KEY_NAME,
    CONFIG_KEY_PROTOCOL,
    CONFIG_KEY_POLICY,
    CONFIG_KEY_PORT,
    CONFIG_KEY_SUBNET,
    CONFIG_KEY_USERS,
    CONFIG_KEY_ALLOW_TO_LAN,
    CONFIG_KEY_ALLOW_TO_ROUTER,
    CONFIG_KEY_AWG,
}


def require_known_keys(raw: dict[str, object], where: str, allowed: set[str]) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        die(f"{where}: unknown config key(s): {', '.join(unknown)}")


def normalize_config_package_list(
    value: object,
    where: str,
    *,
    allow_empty: bool,
    router_override: bool,
) -> list[str]:
    if not isinstance(value, list):
        die(f"{where} must be a list of strings")
    if not value and not allow_empty:
        die(f"{where} must be a non-empty list of strings")

    result: list[str] = []
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
            package = item[1:]
            if not package:
                die(f"{where} has empty package entry: {item}")
            require_package_identifier(package, f"{where} package entry {item!r}")
        else:
            if item[0] in "+-":
                die(f"{where} entries must not start with + or -: {item}")
            require_package_identifier(item, f"{where} package entry {item!r}")

        result.append(item)

    return result


def validate_config_package_list(
    value: object,
    where: str,
    *,
    allow_empty: bool,
    router_override: bool,
) -> None:
    normalize_config_package_list(
        value,
        where,
        allow_empty=allow_empty,
        router_override=router_override,
    )


def normalize_openwrt_version(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{where} must be a non-empty string")

    version = value.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        die(f"{where} must be numeric and >= {MIN_OPENWRT_VERSION_TEXT}: " f"{version}")

    parts = version.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    if (major, minor) < MIN_OPENWRT_VERSION:
        die(f"{where} must be >= {MIN_OPENWRT_VERSION_TEXT}")

    return version


def validate_exit_order_shape(value: object, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or not value:
        die(f"{where} must be a non-empty list of exit hub names")

    seen: set[str] = set()
    for idx, name in enumerate(value, start=1):
        if isinstance(name, list):
            die(
                f"{where}[{idx}] must be an exit hub name, "
                "not a nested list; same-priority exit groups are not supported"
            )
        if not isinstance(name, str) or not name:
            die(f"{where}[{idx}] must be a non-empty exit hub name")
        if name in seen:
            die(f"{where}: duplicate exit hub name: {name}")
        seen.add(name)


def validate_config_known_keys(raw_cfg: dict[str, object]) -> None:
    require_known_keys(raw_cfg, "config", CONFIG_KEYS)

    validate_exit_order_shape(raw_cfg.get(CONFIG_KEY_EXIT_ORDER), "config.exit_order")

    raw_ssh_key_dir = raw_cfg.get(CONFIG_KEY_SSH_KEY_DIR)
    if raw_ssh_key_dir is None:
        die(
            f"missing required config key {CONFIG_KEY_SSH_KEY_DIR!r}; "
            "set it explicitly, for example: "
            '"ssh_key_dir": "~/.ssh/router-autoinstall-prod"'
        )
    if not isinstance(raw_ssh_key_dir, str) or not raw_ssh_key_dir.strip():
        die(f"config.{CONFIG_KEY_SSH_KEY_DIR} must be a non-empty string")

    raw_secret_key = raw_cfg.get(CONFIG_KEY_SECRET_KEY)
    if raw_secret_key is not None:
        if not isinstance(raw_secret_key, str) or not raw_secret_key.strip():
            die(f"config.{CONFIG_KEY_SECRET_KEY} must be a non-empty string")

    normalize_openwrt_version(
        raw_cfg.get(CONFIG_KEY_OPENWRT_VERSION),
        "config.openwrt_version",
    )

    raw_packages = raw_cfg.get(CONFIG_KEY_PACKAGES)
    if raw_packages is not None:
        validate_config_package_list(
            raw_packages,
            "config.packages",
            allow_empty=True,
            router_override=False,
        )

    raw_profiles = raw_cfg.get(CONFIG_KEY_DEVICE_PROFILES, {})
    if raw_profiles is not None:
        if not isinstance(raw_profiles, dict):
            die("config key 'device_profiles' must be an object")
        for profile_name, profile in raw_profiles.items():
            require_file_identifier(
                profile_name,
                f"device_profiles[{profile_name}] profile name",
            )
            if not isinstance(profile, dict):
                die(f"device_profiles[{profile_name}] must be an object")
            where = f"device_profiles[{profile_name}]"
            require_known_keys(profile, where, DEVICE_PROFILE_KEYS)
            require_device_profile_board(
                profile.get(CONFIG_KEY_BOARD), f"{where}.board"
            )
            require_device_profile_arch(profile.get(CONFIG_KEY_ARCH), f"{where}.arch")

    raw_routers = raw_cfg.get(CONFIG_KEY_ROUTERS, [])
    if raw_routers is not None:
        if not isinstance(raw_routers, list):
            die("config key 'routers' must be a list")
        for idx, raw in enumerate(raw_routers, start=1):
            if not isinstance(raw, dict):
                die(f"routers[{idx}] must be an object")
            name = raw.get(CONFIG_KEY_NAME, idx)
            where = f"routers[{name}]"
            require_known_keys(raw, where, ROUTER_KEYS)

            validate_exit_order_shape(
                raw.get(CONFIG_KEY_EXIT_ORDER),
                f"{where}.exit_order",
            )

            packages = raw.get(CONFIG_KEY_PACKAGES)
            if packages is not None:
                validate_config_package_list(
                    packages,
                    f"{where}.packages",
                    allow_empty=True,
                    router_override=True,
                )

            profile_name = raw.get(CONFIG_KEY_DEVICE_PROFILE)
            if profile_name is None:
                die(f"{where}.device_profile is required")
            if not isinstance(profile_name, str) or not profile_name:
                die(f"{where}.device_profile must be a non-empty string")
            require_file_identifier(profile_name, f"{where}.device_profile")
            raw_profiles_for_check = raw_cfg.get(CONFIG_KEY_DEVICE_PROFILES, {})
            if (
                isinstance(raw_profiles_for_check, dict)
                and profile_name not in raw_profiles_for_check
            ):
                die(
                    f"{where}.device_profile references unknown profile: {profile_name}"
                )

            for wifi_key in WIFI_CONFIG_KEYS:
                wifi = raw.get(wifi_key)
                if wifi is not None:
                    if not isinstance(wifi, dict):
                        die(f"{where}.{wifi_key} must be an object")
                    require_known_keys(wifi, f"{where}.{wifi_key}", WIFI_KEYS)

    raw_mesh_hubs = raw_cfg.get(CONFIG_KEY_MESH_HUBS, [])
    if raw_mesh_hubs is not None:
        if not isinstance(raw_mesh_hubs, list):
            die("config key 'mesh_hubs' must be a list")
        for idx, raw in enumerate(raw_mesh_hubs, start=1):
            if not isinstance(raw, dict):
                die(f"mesh_hubs[{idx}] must be an object")
            name = raw.get(CONFIG_KEY_NAME, idx)
            where = f"mesh_hubs[{name}]"
            require_known_keys(raw, where, MESH_HUB_KEYS)
            access_only = raw.get(CONFIG_KEY_ACCESS_ONLY)
            if access_only is not None and not isinstance(access_only, bool):
                die(f"{where}.access_only must be a boolean")

    raw_exit_hubs = raw_cfg.get(CONFIG_KEY_EXIT_HUBS, [])
    if raw_exit_hubs is not None:
        if not isinstance(raw_exit_hubs, list):
            die("config key 'exit_hubs' must be a list")
        for idx, raw in enumerate(raw_exit_hubs, start=1):
            if not isinstance(raw, dict):
                die(f"exit_hubs[{idx}] must be an object")
            name = raw.get(CONFIG_KEY_NAME, idx)
            where = f"exit_hubs[{name}]"
            require_known_keys(raw, where, EXIT_HUB_KEYS)

    load_exit_direct_config()

    raw_access = raw_cfg.get(CONFIG_KEY_ACCESS, {})
    if raw_access is not None:
        if not isinstance(raw_access, dict):
            die("config key 'access' must be an object")
        for router_name, groups in raw_access.items():
            if not isinstance(groups, list):
                die(f"access[{router_name}] must be a list")
            for idx, raw in enumerate(groups, start=1):
                if not isinstance(raw, dict):
                    die(f"access[{router_name}][{idx}] must be an object")
                iface_name = raw.get(CONFIG_KEY_NAME, idx)
                access_where = f"access[{router_name}][{iface_name}]"
                require_known_keys(
                    raw,
                    access_where,
                    ACCESS_KEYS,
                )
                awg = raw.get(CONFIG_KEY_AWG)
                if awg is not None:
                    if not isinstance(awg, dict):
                        die(f"{access_where}.awg must be an object")
                    require_known_keys(awg, f"{access_where}.awg", AWG_KEYS)


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def need(*names: str) -> None:
    for name in names:
        if shutil.which(name) is None:
            die(f"command not found: {name}")


def sh(args: list[str], input_text: str | None = None) -> str:
    res = subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=True,
    )
    return res.stdout.strip()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return

    print(f"Updating {path}")
    old_mode = path.stat().st_mode if path.exists() else None

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)

    if old_mode is not None:
        tmp_path.chmod(old_mode)

    tmp_path.replace(path)


def rm(path: Path) -> None:
    if not path.exists():
        return
    print(f"Removing {path}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def cp_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if not src.is_dir():
        die(f"template path is not a directory: {src}")

    for item in src.rglob("*"):
        out = dst / item.relative_to(src)
        if item.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if item.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() and item.read_bytes() == out.read_bytes():
                continue
            print(f"Updating {out}")
            shutil.copy2(item, out)


def parse_ipv4(ip: str) -> list[int]:
    if not CANONICAL_IPV4_RE.fullmatch(ip):
        raise ValueError(ip)
    parts = ip.split(".")
    if len(parts) != IPV4_OCTET_COUNT:
        raise ValueError(ip)
    nums = [int(x) for x in parts]
    if any(n < IPV4_OCTET_MIN or n > IPV4_OCTET_MAX for n in nums):
        raise ValueError(ip)
    return nums


def canonical_ipv4(ip: str) -> str:
    return ".".join(str(n) for n in parse_ipv4(ip))


def require_usable_unicast_ipv4_address(ip: str, where: str) -> None:
    addr = ipaddress.IPv4Address(ip)
    if (
        addr.is_unspecified
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or ip == "255.255.255.255"
    ):
        die(f"{where} must be a usable unicast IPv4 address: {ip}")


def ipv4_without_prefix(ip: str) -> str:
    return ip.split("/", 1)[0]


def ipv4_to_link_local(ipv4_with_prefix: str) -> str:
    nums = parse_ipv4(ipv4_with_prefix.split("/", 1)[0])
    return f"fe80::{nums[0]}:{nums[1]}:{nums[2]}:{nums[3]}/{IPV4_LINK_LOCAL_PREFIXLEN}"


def host_ip_in_prefix(prefix: str, host: int, cidr: int) -> str:
    return f"{prefix}.{host}/{cidr}"


def normalize_listen_ip(value: object, where: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        die(f"{where} must be an IPv4 address string when set")
    host = value.strip()
    if not host:
        return ""
    if ":" in host:
        die(f"{where} must contain only IPv4 address without port: {host}")
    try:
        ip = canonical_ipv4(host)
    except ValueError:
        die(f"{where} must be a canonical IPv4 address when set: {host}")
    require_usable_unicast_ipv4_address(ip, where)
    return ip


def load_bool(value: object, where: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        die(f"{where} must be a boolean")
    return value


def normalize_optional_exit_ip(value: object, where: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        die(f"{where} must be an IPv4 address string when set")
    host = value.strip()
    if not host:
        return ""
    if ":" in host:
        die(f"{where} must contain only IPv4 address without port: {host}")
    try:
        ip = canonical_ipv4(host)
    except ValueError:
        die(f"{where} must be a canonical IPv4 address when set: {host}")
    require_usable_unicast_ipv4_address(ip, where)
    return ip


def stable_generated_network_for_key(
    *,
    key: str,
    keys: list[str],
    supernet_text: str,
    prefixlen: int,
    purpose: str,
    where: str,
) -> ipaddress.IPv4Network:
    supernet = ipaddress.IPv4Network(supernet_text, strict=True)
    if prefixlen < supernet.prefixlen:
        die(
            f"bad {where} prefix length /{prefixlen}: "
            f"must be >= supernet prefix length /{supernet.prefixlen}"
        )
    if prefixlen > 31:
        die(f"bad {where} prefix length /{prefixlen}: no usable host address")

    subnet_size = 1 << (32 - prefixlen)
    group_count = 1 << (prefixlen - supernet.prefixlen)
    unique_keys = sorted(set(keys))
    if key not in unique_keys:
        die(f"{where}: key {key!r} is not in allocation key set")

    index = stable_unique_values(
        unique_keys,
        start=0,
        end=group_count - 1,
        purpose=purpose,
        where=f"{where} in {supernet}",
    )[key]
    network_addr = int(supernet.network_address) + index * subnet_size
    return ipaddress.IPv4Network((network_addr, prefixlen), strict=True)


def generated_exit_announce_network(
    name: str, all_names: list[str]
) -> ipaddress.IPv4Network:
    return stable_generated_network_for_key(
        key=name,
        keys=all_names,
        supernet_text=EXIT_ANNOUNCE_SUPERNET4,
        prefixlen=EXIT_ANNOUNCE_PREFIXLEN,
        purpose="exit-announce",
        where="exit announce prefixes",
    )


def generated_exit_node_network(
    name: str, all_names: list[str]
) -> ipaddress.IPv4Network:
    return stable_generated_network_for_key(
        key=name,
        keys=all_names,
        supernet_text=EXIT_NODE_SUPERNET4,
        prefixlen=EXIT_NODE_PREFIXLEN,
        purpose="exit-node",
        where="exit node prefixes",
    )


def generated_exit_node_ip(name: str, all_names: list[str]) -> str:
    network = generated_exit_node_network(name, all_names)
    return str(network.network_address)


def exit_announce_network(hub: ExitHub) -> ipaddress.IPv4Network:
    if not hub.announce:
        die(f"exit hub {hub.name} has no generated announce network")
    return ipaddress.IPv4Network(hub.announce, strict=True)


def exit_announce_target_ip(hub: ExitHub) -> str:
    network = exit_announce_network(hub)
    return str(ipaddress.IPv4Address(int(network.network_address) + 1))


def exit_dummy_addr4(hub: ExitHub) -> str:
    network = exit_announce_network(hub)
    return f"{exit_announce_target_ip(hub)}/{network.prefixlen}"


def exit_ipip_endpoint_addr4(hub: ExitHub) -> str:
    return exit_dummy_addr4(hub)


def exit_node_network(hub: ExitHub) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(
        f"{hub.node_ip}/{P2P_LINK_PREFIXLEN}",
        strict=False,
    )


def exit_node_prefix(hub: ExitHub) -> str:
    return str(exit_node_network(hub))


def exit_node_addr4(hub: ExitHub) -> str:
    return f"{hub.node_ip}/{exit_node_network(hub).prefixlen}"


def exit_ipip_endpoint_ip(hub: ExitHub) -> str:
    return exit_announce_target_ip(hub)


def router_exit_ipip_iface_name(hub_name: str) -> str:
    # exit_hubs.name is already validated as uppercase ASCII and max 8 bytes.
    # OpenWrt ipip proto creates a Linux device named f"ipip-ip{hub_name}",
    # which therefore always fits the 15-byte visible Linux interface limit.
    return f"ip{hub_name}"


def load_exit_order_groups(
    value: object,
    where: str,
    exit_hubs_by_name: dict[str, ExitHub],
    *,
    require_all: bool,
) -> list[list[str]]:
    if value is None:
        return []

    validate_exit_order_shape(value, where)
    assert isinstance(value, list)

    groups: list[list[str]] = []
    seen: set[str] = set()
    for idx, name in enumerate(value, start=1):
        assert isinstance(name, str)
        if name not in exit_hubs_by_name:
            die(f"{where}: unknown exit hub name: {name}")
        if name in seen:
            die(f"{where}: duplicate exit hub name: {name}")
        seen.add(name)
        groups.append([name])

    if require_all:
        missing = [name for name in sorted(exit_hubs_by_name) if name not in seen]
        if missing:
            die(
                f"{where} must list every exit_hubs name exactly once; "
                f"missing: {', '.join(missing)}"
            )

    return groups


def load_exit_order_names(
    value: object,
    where: str,
    exit_hubs_by_name: dict[str, ExitHub],
    *,
    require_all: bool,
) -> list[str]:
    groups = load_exit_order_groups(
        value,
        where,
        exit_hubs_by_name,
        require_all=require_all,
    )
    return [name for group in groups for name in group]


def assign_generated_exit_announces(
    hubs: list[ExitHub],
    order_groups: list[list[str]],
) -> list[ExitHub]:
    # exit_order still controls user-facing preference order, but marker
    # prefixes are now stable hash-selected by exit name so reordering exits
    # does not move 10.254.0.0/24 announcements.
    hubs_by_name = {hub.name: hub for hub in hubs}
    if not order_groups:
        order_groups = [[hub.name] for hub in sorted(hubs, key=lambda h: h.name)]

    seen: set[str] = set()
    for group in order_groups:
        for name in group:
            if name not in hubs_by_name:
                die(f"config.exit_order references unknown exit hub: {name}")
            if name in seen:
                die(f"config.exit_order contains duplicate exit hub name: {name}")
            seen.add(name)

    missing = [name for name in sorted(hubs_by_name) if name not in seen]
    if missing:
        die(
            "config.exit_order must list every exit_hubs name exactly once; "
            f"missing: {', '.join(missing)}"
        )

    all_names = sorted(hubs_by_name)
    out: list[ExitHub] = []
    for hub in hubs:
        node_ip = hub.node_ip or generated_exit_node_ip(hub.name, all_names)
        out.append(
            ExitHub(
                name=hub.name,
                node_ip=node_ip,
                listen_ip=hub.listen_ip,
                exit_ip=hub.exit_ip,
                announce=str(generated_exit_announce_network(hub.name, all_names)),
                port_range=hub.port_range,
            )
        )
    return sorted(out, key=lambda h: h.name)


def router_exit_order_hubs(
    cfg: ConfigData, router_name: str | None = None
) -> list[ExitHub]:
    order: list[str] = []
    if router_name is not None:
        if router_name not in cfg.router_by_name:
            die(f"unknown router for exit route targets: {router_name}")
        order = cfg.exit_order_by_router.get(router_name, [])
    if not order:
        order = cfg.exit_order
    if not order:
        order = [hub.name for hub in cfg.exit_hubs]
    return [cfg.exit_hubs_by_name[name] for name in order]


def validate_exit_announce_set(hubs: list[ExitHub]) -> None:
    networks = [exit_announce_network(hub) for hub in hubs]
    if not networks:
        return

    prefixlen = networks[0].prefixlen
    for hub, network in zip(hubs, networks):
        if network.prefixlen != prefixlen:
            die(
                f"generated announce for exit_hubs[{hub.name}] uses /{network.prefixlen}; "
                f"all generated announce prefixes must use the same prefix length /{prefixlen}"
            )

    unique = sorted(set(networks), key=lambda n: int(n.network_address))
    for i, left in enumerate(unique):
        for right in unique[i + 1 :]:
            if left.overlaps(right):
                die(
                    f"generated exit announce prefixes must not overlap: {left} overlaps {right}"
                )


def unique_preserve_order(items: list[str], where: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for item in items:
        if item in seen:
            die(f"{where}: duplicate entry: {item}")
        seen.add(item)
        out.append(item)

    return out


def normalize_exit_direct_subnet(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{where} must be a non-empty IPv4 CIDR")
    raw = value.strip()

    try:
        network = ipaddress.IPv4Network(raw, strict=False)
    except ValueError as e:
        die(f"{where} must be an IPv4 CIDR: {e}")

    return str(network)


def normalize_exit_direct_country(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{where} must be a two-letter country code")
    country = value.strip().lower()
    if not re.fullmatch(r"[a-z]{2}", country):
        die(f"{where} must be a two-letter country code: {value}")
    return country


def normalize_exit_direct_asn(value: object, where: str) -> str:
    if isinstance(value, int):
        asn = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        asn = int(value.strip())
    else:
        die(f"{where} must be an integer ASN")

    if asn <= 0 or asn > 4294967295:
        die(f"{where} must be in 1..4294967295")

    return str(asn)


def load_exit_direct_config() -> ExitDirectConfig:
    subnets = unique_preserve_order(
        [
            normalize_exit_direct_subnet(
                item,
                f"default.EXIT_DIRECT_STATIC_IPSETS[{idx}]",
            )
            for idx, item in enumerate(EXIT_DIRECT_STATIC_IPSETS, start=1)
        ],
        "default.EXIT_DIRECT_STATIC_IPSETS",
    )
    countries = unique_preserve_order(
        [
            normalize_exit_direct_country(
                item,
                f"default.EXIT_DIRECT_COUNTRIES[{idx}]",
            )
            for idx, item in enumerate(EXIT_DIRECT_COUNTRIES, start=1)
        ],
        "default.EXIT_DIRECT_COUNTRIES",
    )
    asns = unique_preserve_order(
        [
            normalize_exit_direct_asn(
                item,
                f"default.EXIT_DIRECT_ASNS[{idx}]",
            )
            for idx, item in enumerate(EXIT_DIRECT_ASNS, start=1)
        ],
        "default.EXIT_DIRECT_ASNS",
    )

    return ExitDirectConfig(subnets=subnets, countries=countries, asns=asns)


def parse_port_range_value(value: object, where: str) -> PortRange:
    if not isinstance(value, str):
        die(f"{where} must be like '20000-32767'")

    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
    if not m:
        die(f"{where} must be like '20000-32767'")

    start = int(m.group(1))
    end = int(m.group(2))
    if start < PORT_MIN or end > PORT_MAX or start > end:
        die(f"{where} must be within {PORT_MIN}..{PORT_MAX} and start <= end")

    return PortRange(start=start, end=end)


def infra_awg_port_range() -> PortRange:
    return parse_port_range_value(INFRA_AWG_PORT_RANGE, "INFRA_AWG_PORT_RANGE")


def normalize_ipv4_subnet_24_prefix(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{where} must be an IPv4 /24 subnet like '10.10.1.0/24'")

    raw = value.strip()
    m = re.fullmatch(
        r"((?:0|[1-9][0-9]{0,2}))"
        r"\.((?:0|[1-9][0-9]{0,2}))"
        r"\.((?:0|[1-9][0-9]{0,2}))"
        r"\.0/24",
        raw,
    )
    if not m:
        die(f"{where} must be a canonical IPv4 /24 subnet like '10.10.1.0/24'")

    nums = [int(x) for x in m.groups()]
    if any(n < IPV4_OCTET_MIN or n > IPV4_OCTET_MAX for n in nums):
        die(f"{where} has invalid octet: {raw}")

    prefix = ".".join(str(n) for n in nums)
    if raw != f"{prefix}.0/24":
        die(f"{where} must be canonical IPv4 /24 subnet: {raw}")

    return prefix


def stable_hex(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def stable_hash_u32(seed: str) -> int:
    digest = hashlib.blake2s(
        seed.encode("utf-8"), digest_size=STABLE_HASH_U32_DIGEST_SIZE
    ).digest()
    return int.from_bytes(digest, "big")


def stable_unique_values(
    keys: list[str],
    *,
    start: int,
    end: int,
    purpose: str,
    where: str,
) -> dict[str, int]:
    if start > end:
        die(f"{where}: invalid allocation range {start}..{end}")

    span = end - start + 1
    if len(keys) > span:
        die(f"{where}: cannot allocate {len(keys)} unique values in {start}..{end}")

    used: set[int] = set()
    result: dict[str, int] = {}

    for key in sorted(keys):
        for attempt in range(span):
            value = start + (stable_hash_u32(f"{key}:{purpose}:{attempt}") % span)
            if value in used:
                continue
            used.add(value)
            result[key] = value
            break
        else:
            die(f"{where}: cannot allocate unique {purpose} for {key}")

    return result


def mesh_link_key(hub_name: str, target_name: str) -> str:
    return f"mesh:{hub_name}:{target_name}"


def ring_link_pairs(names: list[str]) -> list[tuple[str, str]]:
    # Keep the order provided by the caller.  The current config loader passes
    # mesh hubs in lexical order, so mesh rings are lexical unless a different
    # caller deliberately supplies another order.
    ordered = list(names)
    if len(ordered) < 2:
        return []
    if len(ordered) == 2:
        return [(ordered[0], ordered[1])]
    return [(ordered[i], ordered[(i + 1) % len(ordered)]) for i in range(len(ordered))]


def mesh_link_specs(cfg: ConfigData) -> list[tuple[str, str]]:
    # Topology policy:
    #   * every leaf/router connects to every public spine hub;
    #   * spine-to-spine core is a ring with one full-duplex tunnel per edge.
    spine_names = {hub.name for hub in cfg.mesh_hubs}
    spine_order = [hub.name for hub in cfg.mesh_hubs]
    specs: list[tuple[str, str]] = []

    for hub in cfg.mesh_hubs:
        for router_name in cfg.router_names:
            if router_name not in spine_names:
                specs.append((hub.name, router_name))

    # Spine ring is expressed as clockwise client/Out -> server/In sessions.
    # compute_mesh_link_params(hub, target) treats hub as listener/server-side
    # and target as client/initiator-side, so reverse each clockwise edge.
    specs.extend(
        (server_name, client_name)
        for client_name, server_name in ring_link_pairs(spine_order)
    )
    return specs


def mesh_link_specs_for_hub(cfg: ConfigData, hub_name: str) -> list[tuple[str, str]]:
    return [(hub, target) for hub, target in mesh_link_specs(cfg) if hub == hub_name]


def mesh_link_specs_for_router(
    cfg: ConfigData, router_name: str
) -> list[tuple[str, str]]:
    return [
        (hub, target)
        for hub, target in mesh_link_specs(cfg)
        if hub == router_name or target == router_name
    ]


def mesh_iface_names_for_router(cfg: ConfigData, router_name: str) -> set[str]:
    names: set[str] = set()
    for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
        if router_name == hub_name:
            names.add(mesh_server_iface_name_for_target(target_name))
        if router_name == target_name:
            names.add(client_iface_name_for_target(cfg, router_name, hub_name))
    return names


def exit_link_key(hub_name: str, router_name: str) -> str:
    return f"exit:{hub_name}:{router_name}"


def exit_reverse_link_key(hub_name: str, router_name: str) -> str:
    return f"exit-reverse:{hub_name}:{router_name}"


def exit_exit_pair_names(left_name: str, right_name: str) -> tuple[str, str]:
    if left_name == right_name:
        die(f"bad exit-exit pair: {left_name} == {right_name}")
    return left_name, right_name


def exit_exit_link_key(client_name: str, server_name: str) -> str:
    client, server = exit_exit_pair_names(client_name, server_name)
    return f"exit-exit:{client}:{server}"


def mesh_link_keys(cfg: ConfigData, hub: MeshHub) -> list[str]:
    return [
        mesh_link_key(hub_name, target_name)
        for hub_name, target_name in mesh_link_specs_for_hub(cfg, hub.name)
    ]


def exit_link_keys(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return [exit_link_key(hub.name, name) for name in cfg.router_names]


def exit_reverse_link_keys(cfg: ConfigData) -> list[str]:
    return [
        exit_reverse_link_key(hub.name, mesh_hub.name)
        for hub in cfg.exit_hubs
        for mesh_hub in cfg.mesh_hubs
    ]


def public_exit_hub_names(cfg: ConfigData) -> list[str]:
    hubs_by_name = cfg.exit_hubs_by_name
    order = cfg.exit_order or [hub.name for hub in cfg.exit_hubs]
    return [name for name in order if hubs_by_name[name].listen_ip]


def exit_exit_link_pairs(cfg: ConfigData) -> list[tuple[str, str]]:
    # Exit-to-exit layer is a clockwise ring over public exits only.
    # A grey/NAT exit is skipped here; it still connects to every spine through
    # exit-in/reverse links, but it is not used as an exit-exit listener.
    #
    # Pair direction is part of the generated session semantics:
    #   client/Out -> server/In
    return ring_link_pairs(public_exit_hub_names(cfg))


def exit_exit_link_pair_for_hubs(
    cfg: ConfigData, left_name: str, right_name: str
) -> tuple[str, str]:
    for client_name, server_name in exit_exit_link_pairs(cfg):
        if (left_name, right_name) in (
            (client_name, server_name),
            (server_name, client_name),
        ):
            return client_name, server_name
    die(f"exit-exit link is not configured: {left_name}<->{right_name}")


def exit_exit_peer_names_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    peers: list[str] = []
    for client_name, server_name in exit_exit_link_pairs(cfg):
        if hub.name == client_name:
            peers.append(server_name)
        elif hub.name == server_name:
            peers.append(client_name)
    return sorted(peers)


def exit_exit_link_keys(cfg: ConfigData) -> list[str]:
    return [
        exit_exit_link_key(client_name, server_name)
        for client_name, server_name in exit_exit_link_pairs(cfg)
    ]


def exit_exit_link_keys_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return [
        exit_exit_link_key(*exit_exit_link_pair_for_hubs(cfg, hub.name, peer_name))
        for peer_name in exit_exit_peer_names_for_hub(cfg, hub)
    ]


def stable_unique_values_avoiding(
    keys: list[str],
    *,
    start: int,
    end: int,
    purpose: str,
    where: str,
    reserved: set[int] | None = None,
) -> dict[str, int]:
    reserved = set(reserved or set())
    if start > end:
        die(f"{where}: invalid allocation range {start}..{end}")

    span = end - start + 1
    if len(keys) + len(reserved) > span:
        die(
            f"{where}: cannot allocate {len(keys)} unique values in {start}..{end} "
            f"with {len(reserved)} reserved values"
        )

    used: set[int] = set(reserved)
    result: dict[str, int] = {}

    for key in sorted(keys):
        for attempt in range(span):
            value = start + (stable_hash_u32(f"{key}:{purpose}:{attempt}") % span)
            if value in used:
                continue
            used.add(value)
            result[key] = value
            break
        else:
            die(f"{where}: cannot allocate unique {purpose} for {key}")

    return result


def stable_port_for(
    port_range: PortRange,
    keys: list[str],
    key: str,
    where: str,
) -> int:
    return stable_unique_values(
        keys,
        start=port_range.start,
        end=port_range.end,
        purpose="port",
        where=where,
    )[key]


def stable_port_avoiding_for(
    port_range: PortRange,
    keys: list[str],
    key: str,
    where: str,
    reserved: set[int],
) -> int:
    return stable_unique_values_avoiding(
        keys,
        start=port_range.start,
        end=port_range.end,
        purpose="port",
        where=where,
        reserved=reserved,
    )[key]


def infra_link_keys(cfg: ConfigData) -> list[str]:
    # Mesh-mesh and router-exit link keys are kept unchanged so adding
    # exit-exit links does not move existing /31 allocations.
    keys: list[str] = []

    for hub in cfg.mesh_hubs:
        keys.extend(mesh_link_keys(cfg, hub))

    for hub in cfg.exit_hubs:
        keys.extend(exit_link_keys(cfg, hub))

    return sorted(keys)


def stable_infra_link_pair_indices(
    cfg: ConfigData,
) -> tuple[ipaddress.IPv4Network, int, dict[str, int]]:
    pool = ipaddress.IPv4Network(INFRA_LINK_POOL, strict=True)
    if pool.prefixlen > P2P_LINK_PREFIXLEN:
        die(f"infra link pool {pool} is too small for /{P2P_LINK_PREFIXLEN} links")

    pair_count = pool.num_addresses // P2P_LINK_HOST_STRIDE
    allocated = stable_unique_values(
        infra_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"infra link addresses in {pool}",
    )
    return pool, pair_count, allocated


def infra_link_network_from_pair_index(
    pool: ipaddress.IPv4Network,
    pair_index: int,
    where: str,
) -> ipaddress.IPv4Network:
    first_ip = int(pool.network_address) + pair_index * P2P_LINK_HOST_STRIDE
    network = ipaddress.IPv4Network((first_ip, P2P_LINK_PREFIXLEN), strict=True)
    if network.network_address not in pool or network.broadcast_address not in pool:
        die(f"{where}: generated link {network} is outside infra pool {pool}")
    return network


def stable_infra_link_network_for(
    cfg: ConfigData, key: str, where: str
) -> ipaddress.IPv4Network:
    pool, _pair_count, allocated = stable_infra_link_pair_indices(cfg)
    return infra_link_network_from_pair_index(pool, allocated[key], where)


def stable_exit_exit_link_network_for(
    cfg: ConfigData, key: str, where: str
) -> ipaddress.IPv4Network:
    pool, pair_count, existing_allocated = stable_infra_link_pair_indices(cfg)
    pair_index = stable_unique_values_avoiding(
        exit_exit_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"exit-exit link addresses in {pool}",
        reserved=set(existing_allocated.values()),
    )[key]
    return infra_link_network_from_pair_index(pool, pair_index, where)


def stable_exit_reverse_link_network_for(
    cfg: ConfigData, key: str, where: str
) -> ipaddress.IPv4Network:
    pool, pair_count, existing_allocated = stable_infra_link_pair_indices(cfg)
    exit_exit_allocated = stable_unique_values_avoiding(
        exit_exit_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"exit-exit link addresses in {pool}",
        reserved=set(existing_allocated.values()),
    )
    reserved = set(existing_allocated.values()) | set(exit_exit_allocated.values())
    pair_index = stable_unique_values_avoiding(
        exit_reverse_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"exit-reverse link addresses in {pool}",
        reserved=reserved,
    )[key]
    return infra_link_network_from_pair_index(pool, pair_index, where)


def link_network_addresses(network: ipaddress.IPv4Network) -> tuple[str, str]:
    addrs = list(network.hosts())
    if len(addrs) != P2P_LINK_HOST_STRIDE:
        die(f"generated link {network} is not a two-address /{P2P_LINK_PREFIXLEN}")
    return (
        f"{addrs[0]}/{P2P_LINK_PREFIXLEN}",
        f"{addrs[1]}/{P2P_LINK_PREFIXLEN}",
    )


def stable_seed_u64(seed: str) -> int:
    digest = hashlib.blake2b(
        seed.encode("utf-8"), digest_size=STABLE_SEED_U64_DIGEST_SIZE
    ).digest()
    return int.from_bytes(digest, "big")


def random_free_slots(rng: random.Random, total_free: int, slots: int) -> list[int]:
    if slots <= 1:
        return [total_free]
    points = sorted(rng.randrange(total_free + 1) for _ in range(slots - 1))
    values: list[int] = []
    prev = 0
    for point in points:
        values.append(point - prev)
        prev = point
    values.append(total_free - prev)
    return values


def parse_awg_h_range(value: str, where: str) -> tuple[int, int]:
    value = value.strip()
    parts = value.split("-", 1)
    if len(parts) != 2:
        die(f"{where} must be START-END")

    try:
        start = int(parts[0])
        end = int(parts[1])
    except ValueError:
        die(f"{where} must contain integer bounds")

    if start < AWG_H_MIN or end > AWG_H_MAX or start > end:
        die(f"{where} must be in range {AWG_H_MIN}..{AWG_H_MAX} " "and start <= end")

    return start, end


def ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def validate_awg_h_range_strings(values: list[str], where: str) -> None:
    if len(values) != AWG_H_COUNT:
        die(f"{where}: expected {AWG_H_COUNT} AWG H ranges, got {len(values)}")

    parsed: list[tuple[str, tuple[int, int]]] = []
    for idx, value in enumerate(values, start=1):
        name = f"h{idx}"
        parsed.append((name, parse_awg_h_range(value, f"{where}.{name}")))

    for left_idx, (left_name, left) in enumerate(parsed):
        for right_name, right in parsed[left_idx + 1 :]:
            if ranges_overlap(left, right):
                die(
                    f"{where}: AWG H ranges overlap: "
                    f"{left_name}={left[0]}-{left[1]} "
                    f"{right_name}={right[0]}-{right[1]}"
                )


def validate_awg_h_ranges(awg: AwgOptions, where: str) -> None:
    validate_awg_h_range_strings([awg.h1, awg.h2, awg.h3, awg.h4], where)


def validate_awg_runtime_ranges(awg: AwgOptions, where: str) -> None:
    if awg.jc < AWG_JC_MIN or awg.jc > AWG_JC_MAX:
        die(f"{where}.jc must be in range {AWG_JC_MIN}..{AWG_JC_MAX}")
    if (
        awg.jmin < AWG_JUNK_SIZE_MIN
        or awg.jmin > AWG_JUNK_SIZE_MAX
        or awg.jmax < AWG_JUNK_SIZE_MIN
        or awg.jmax > AWG_JUNK_SIZE_MAX
        or awg.jmin > awg.jmax
    ):
        die(
            f"{where}.jmin/jmax must be in range "
            f"{AWG_JUNK_SIZE_MIN}..{AWG_JUNK_SIZE_MAX} and jmin <= jmax"
        )
    if not (
        AWG_S1_MIN <= awg.s1 <= AWG_S1_MAX
        and AWG_S2_MIN <= awg.s2 <= AWG_S2_MAX
        and AWG_S3_MIN <= awg.s3 <= AWG_S3_MAX
        and AWG_S4_MIN <= awg.s4 <= AWG_S4_MAX
    ):
        die(
            f"{where}.s1 must be {AWG_S1_MIN}..{AWG_S1_MAX}, "
            f"s2 must be {AWG_S2_MIN}..{AWG_S2_MAX}, "
            f"s3 must be {AWG_S3_MIN}..{AWG_S3_MAX}, "
            f"s4 must be {AWG_S4_MIN}..{AWG_S4_MAX}"
        )


def validate_awg_options(awg: AwgOptions, where: str) -> None:
    validate_awg_runtime_ranges(awg, where)
    validate_awg_h_ranges(awg, where)


def validate_awg_auto_ranges() -> None:
    if AWG_INFRA_AUTO_JC_MIN < AWG_JC_MIN or AWG_INFRA_AUTO_JC_MAX > AWG_JC_MAX:
        die("bad AWG_INFRA_AUTO_JC_MIN/AWG_INFRA_AUTO_JC_MAX")
    if AWG_INFRA_AUTO_JC_MIN > AWG_INFRA_AUTO_JC_MAX:
        die("bad AWG_INFRA_AUTO_JC_MIN/AWG_INFRA_AUTO_JC_MAX")
    if (
        AWG_INFRA_AUTO_JUNK_SIZE_MIN < AWG_JUNK_SIZE_MIN
        or AWG_INFRA_AUTO_JUNK_SIZE_MAX > AWG_JUNK_SIZE_MAX
        or AWG_INFRA_AUTO_JUNK_SIZE_MIN > AWG_INFRA_AUTO_JUNK_SIZE_MAX
    ):
        die("bad AWG_INFRA_AUTO_JUNK_SIZE_MIN/AWG_INFRA_AUTO_JUNK_SIZE_MAX")
    if (
        AWG_INFRA_AUTO_S1_MIN < AWG_S1_MIN
        or AWG_INFRA_AUTO_S1_MAX > AWG_S1_MAX
        or AWG_INFRA_AUTO_S1_MIN > AWG_INFRA_AUTO_S1_MAX
    ):
        die("bad AWG_INFRA_AUTO_S1_MIN/AWG_INFRA_AUTO_S1_MAX")
    if (
        AWG_INFRA_AUTO_S2_MIN < AWG_S2_MIN
        or AWG_INFRA_AUTO_S2_MAX > AWG_S2_MAX
        or AWG_INFRA_AUTO_S2_MIN > AWG_INFRA_AUTO_S2_MAX
    ):
        die("bad AWG_INFRA_AUTO_S2_MIN/AWG_INFRA_AUTO_S2_MAX")
    if (
        AWG_INFRA_AUTO_S3_MIN < AWG_S3_MIN
        or AWG_INFRA_AUTO_S3_MAX > AWG_S3_MAX
        or AWG_INFRA_AUTO_S3_MIN > AWG_INFRA_AUTO_S3_MAX
    ):
        die("bad AWG_INFRA_AUTO_S3_MIN/AWG_INFRA_AUTO_S3_MAX")
    if (
        AWG_INFRA_AUTO_S4_MIN < AWG_S4_MIN
        or AWG_INFRA_AUTO_S4_MAX > AWG_S4_MAX
        or AWG_INFRA_AUTO_S4_MIN > AWG_INFRA_AUTO_S4_MAX
    ):
        die("bad AWG_INFRA_AUTO_S4_MIN/AWG_INFRA_AUTO_S4_MAX")


def stable_awg_runtime_params(
    link_key: str,
) -> tuple[int, int, int, int, int, int, int]:
    # Derive per-link AWG runtime parameters from the same stable link key
    # family as ports/link addresses/H-ranges.  This keeps generation
    # deterministic without forcing identical AWG fingerprints on all links.
    validate_awg_auto_ranges()
    rng = random.Random(stable_seed_u64(f"awg-runtime:{link_key}"))

    jc = rng.randint(AWG_INFRA_AUTO_JC_MIN, AWG_INFRA_AUTO_JC_MAX)
    j_left = rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    j_right = rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    jmin, jmax = sorted((j_left, j_right))

    s1 = rng.randint(AWG_INFRA_AUTO_S1_MIN, AWG_INFRA_AUTO_S1_MAX)
    s2 = rng.randint(AWG_INFRA_AUTO_S2_MIN, AWG_INFRA_AUTO_S2_MAX)
    s3 = rng.randint(AWG_INFRA_AUTO_S3_MIN, AWG_INFRA_AUTO_S3_MAX)
    s4 = rng.randint(AWG_INFRA_AUTO_S4_MIN, AWG_INFRA_AUTO_S4_MAX)

    return jc, jmin, jmax, s1, s2, s3, s4


def stable_awg_h_ranges(link_key: str) -> tuple[str, str, str, str]:
    if AWG_H_COUNT != 4:
        die("infra AWG H generation expects AWG_H_COUNT = 4")
    if AWG_H_GAP < 0:
        die("AWG_H_GAP must be non-negative")
    if AWG_H_SPAN_MIN <= 0 or AWG_H_SPAN_MAX < AWG_H_SPAN_MIN:
        die("bad AWG_H_SPAN_MIN/AWG_H_SPAN_MAX")
    if AWG_H_MAX < AWG_H_MIN:
        die("bad AWG_H_MIN/AWG_H_MAX")

    rng = random.Random(stable_seed_u64(f"awg-h:{link_key}"))
    lengths = [rng.randint(AWG_H_SPAN_MIN, AWG_H_SPAN_MAX) for _ in range(AWG_H_COUNT)]

    available = AWG_H_MAX - AWG_H_MIN + 1
    required = sum(lengths) + (len(lengths) - 1) * AWG_H_GAP
    if required > available:
        die(
            "AWG H range is too small for generated spans: "
            f"need {required}, have {available}"
        )

    free_slots = random_free_slots(rng, available - required, len(lengths) + 1)

    ranges: list[str] = []
    pos = AWG_H_MIN + free_slots[0]
    for idx, length in enumerate(lengths):
        start = pos
        end = start + length - 1
        ranges.append(f"{start}-{end}")
        if idx + 1 < len(lengths):
            pos = end + 1 + AWG_H_GAP + free_slots[idx + 1]

    validate_awg_h_range_strings(ranges, f"infra AWG {link_key}")
    return ranges[0], ranges[1], ranges[2], ranges[3]


def awg_for_infra_link(link_key: str) -> AwgOptions:
    h1, h2, h3, h4 = stable_awg_h_ranges(link_key)
    jc, jmin, jmax, s1, s2, s3, s4 = stable_awg_runtime_params(link_key)
    awg = AwgOptions(
        jc=jc,
        jmin=jmin,
        jmax=jmax,
        s1=s1,
        s2=s2,
        s3=s3,
        s4=s4,
        h1=h1,
        h2=h2,
        h3=h3,
        h4=h4,
        i1=AWG_INFRA_I1,
        i2=AWG_INFRA_I2,
        i3=AWG_INFRA_I3,
        i4=AWG_INFRA_I4,
        i5=AWG_INFRA_I5,
    )
    validate_awg_options(awg, f"infra AWG {link_key}")
    return awg


def peer_endpoint(
    *,
    listen_ip: str,
    port: int,
) -> tuple[str, int]:
    return listen_ip, port


def load_json_config(path: Path) -> dict[str, object]:
    if not path.exists():
        die(f"missing config file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse JSON config {path}: {e}")
    if not isinstance(raw, dict):
        die("config must be a JSON object")
    return raw


def load_config_packages(raw_cfg: dict[str, object]) -> list[str]:
    raw_packages = raw_cfg.get(CONFIG_KEY_PACKAGES, [])
    if raw_packages is None:
        raw_packages = []
    return normalize_config_package_list(
        raw_packages,
        "config.packages",
        allow_empty=True,
        router_override=False,
    )


def load_device_profiles(raw_cfg: dict[str, object]) -> dict[str, DeviceProfile]:
    raw_profiles = raw_cfg.get(CONFIG_KEY_DEVICE_PROFILES)
    if not isinstance(raw_profiles, dict):
        die("config key 'device_profiles' must be an object")

    profiles: dict[str, DeviceProfile] = {}
    seen_slugs: dict[str, str] = {}
    for profile_name, raw_profile in raw_profiles.items():
        require_file_identifier(
            profile_name,
            f"device_profiles[{profile_name}] profile name",
        )
        slug = profile_name.lower()
        other_name = seen_slugs.get(slug)
        if other_name is not None:
            die(
                "duplicate device profile name after lowercase: "
                f"{profile_name} conflicts with {other_name}"
            )
        seen_slugs[slug] = profile_name

        if not isinstance(raw_profile, dict):
            die(f"device_profiles[{profile_name}] must be an object")
        where = f"device_profiles[{profile_name}]"
        require_known_keys(raw_profile, where, DEVICE_PROFILE_KEYS)

        board = raw_profile.get(CONFIG_KEY_BOARD)
        arch = raw_profile.get(CONFIG_KEY_ARCH)
        require_device_profile_board(board, f"{where}.board")
        require_device_profile_arch(arch, f"{where}.arch")

        assert isinstance(board, str)
        assert isinstance(arch, str)
        target, subtarget = board.split("/", 1)
        profiles[profile_name] = DeviceProfile(
            name=profile_name,
            board=board,
            arch=arch,
            target=target,
            subtarget=subtarget,
        )

    return profiles


def load_routers(
    raw_cfg: dict[str, object],
    device_profiles: dict[str, DeviceProfile],
) -> list[RouterDef]:
    validate_config_known_keys(raw_cfg)

    routers: list[RouterDef] = []
    seen_names: set[str] = set()
    seen_slugs: dict[str, str] = {}
    seen_subnets: set[str] = set()

    raw_list = raw_cfg.get(CONFIG_KEY_ROUTERS)
    if not isinstance(raw_list, list):
        die("config key 'routers' must be a list")

    for idx, raw in enumerate(raw_list, start=1):
        if not isinstance(raw, dict):
            die("each router entry must be an object")

        name = raw.get(CONFIG_KEY_NAME)

        if not isinstance(name, str) or not name:
            die("router.name must be a non-empty string")
        require_linux_iface_name(
            mesh_server_iface_name_for_target(name),
            f"routers[{idx}].name generated mesh inbound interface",
        )

        subnet_prefix = normalize_ipv4_subnet_24_prefix(
            raw.get(CONFIG_KEY_SUBNET), f"routers[{idx}].subnet"
        )
        subnet = f"{subnet_prefix}.0/{ACCESS_SUBNET_CIDR}"

        profile_name = raw.get(CONFIG_KEY_DEVICE_PROFILE)
        if not isinstance(profile_name, str) or not profile_name:
            die(f"routers[{idx}].device_profile must be a non-empty string")
        require_file_identifier(profile_name, f"routers[{idx}].device_profile")
        if profile_name not in device_profiles:
            die(
                f"routers[{idx}].device_profile references unknown profile: "
                f"{profile_name}"
            )

        raw_packages = raw.get(CONFIG_KEY_PACKAGES, [])
        if raw_packages is None:
            raw_packages = []
        package_overrides = tuple(
            normalize_config_package_list(
                raw_packages,
                f"routers[{name}].packages",
                allow_empty=True,
                router_override=True,
            )
        )

        if name in seen_names:
            die(f"duplicate router.name: {name}")
        slug = name.lower()
        other_name = seen_slugs.get(slug)
        if other_name is not None:
            die(
                f"duplicate router directory name after lowercase: "
                f"{name} conflicts with {other_name}"
            )
        if subnet in seen_subnets:
            die(f"duplicate router.subnet: {subnet}")

        seen_names.add(name)
        seen_slugs[slug] = name
        seen_subnets.add(subnet)
        routers.append(
            RouterDef(
                name=name,
                subnet=subnet,
                device_profile=profile_name,
                package_overrides=package_overrides,
            )
        )

    return routers


def load_awg_options(raw: object, where: str) -> AwgOptions:
    if raw is None:
        die(f"{where}.awg is required for AmneziaWG links")
    if not isinstance(raw, dict):
        die(f"{where}.awg must be an object")
    require_known_keys(raw, f"{where}.awg", AWG_KEYS)

    def get_int(key: str) -> int:
        if key not in raw:
            die(f"{where}.awg.{key} is required")
        try:
            return int(raw[key])
        except Exception:
            die(f"{where}.awg.{key} must be an integer")

    def get_str(key: str, default: str = "") -> str:
        value = raw.get(key, default)
        if value is None:
            return default
        return str(value).strip()

    jc = get_int("jc")
    jmin = get_int("jmin")
    jmax = get_int("jmax")
    s1 = get_int("s1")
    s2 = get_int("s2")
    s3 = get_int("s3")
    s4 = get_int("s4")

    awg = AwgOptions(
        jc=jc,
        jmin=jmin,
        jmax=jmax,
        s1=s1,
        s2=s2,
        s3=s3,
        s4=s4,
        h1=get_str("h1"),
        h2=get_str("h2"),
        h3=get_str("h3"),
        h4=get_str("h4"),
        i1=get_str("i1"),
        i2=get_str("i2"),
        i3=get_str("i3"),
        i4=get_str("i4"),
        i5=get_str("i5"),
    )
    validate_awg_options(awg, f"{where}.awg")
    return awg


def awg_uci_options(awg: AwgOptions) -> dict[str, str]:
    return {
        "awg_jc": str(awg.jc),
        "awg_jmin": str(awg.jmin),
        "awg_jmax": str(awg.jmax),
        "awg_s1": str(awg.s1),
        "awg_s2": str(awg.s2),
        "awg_s3": str(awg.s3),
        "awg_s4": str(awg.s4),
        "awg_h1": str(awg.h1),
        "awg_h2": str(awg.h2),
        "awg_h3": str(awg.h3),
        "awg_h4": str(awg.h4),
        **({"awg_i1": awg.i1} if awg.i1 else {}),
        **({"awg_i2": awg.i2} if awg.i2 else {}),
        **({"awg_i3": awg.i3} if awg.i3 else {}),
        **({"awg_i4": awg.i4} if awg.i4 else {}),
        **({"awg_i5": awg.i5} if awg.i5 else {}),
    }


def awg_conf_lines(awg: AwgOptions) -> list[str]:
    return [
        f"Jc = {awg.jc}",
        f"Jmin = {awg.jmin}",
        f"Jmax = {awg.jmax}",
        f"S1 = {awg.s1}",
        f"S2 = {awg.s2}",
        f"S3 = {awg.s3}",
        f"S4 = {awg.s4}",
        f"H1 = {awg.h1}",
        f"H2 = {awg.h2}",
        f"H3 = {awg.h3}",
        f"H4 = {awg.h4}",
        *([f"I1 = {awg.i1}"] if awg.i1 else []),
        *([f"I2 = {awg.i2}"] if awg.i2 else []),
        *([f"I3 = {awg.i3}"] if awg.i3 else []),
        *([f"I4 = {awg.i4}"] if awg.i4 else []),
        *([f"I5 = {awg.i5}"] if awg.i5 else []),
    ]


def load_mesh_hubs_and_access_endpoints(
    raw_cfg: dict[str, object],
) -> tuple[list[MeshHub], dict[str, str]]:
    hubs: list[MeshHub] = []
    access_endpoints: dict[str, str] = {}
    seen_names: set[str] = set()
    seen_slugs: dict[str, str] = {}
    seen_listen_ips: dict[str, str] = {}

    raw_list = raw_cfg.get(CONFIG_KEY_MESH_HUBS, [])
    if not isinstance(raw_list, list):
        die("config key 'mesh_hubs' must be a list")

    for raw in raw_list:
        if not isinstance(raw, dict):
            die("each mesh_hubs entry must be an object")

        name = raw.get(CONFIG_KEY_NAME)
        if not isinstance(name, str) or not name:
            die("mesh_hubs.name must be a non-empty string")
        require_linux_iface_name(
            mesh_server_iface_name_for_target(name),
            f"mesh_hubs[{name}].name generated mesh inbound interface",
        )
        where = f"mesh_hubs[{name}]"
        require_known_keys(raw, where, MESH_HUB_KEYS)

        if name in seen_names:
            die(f"duplicate mesh_hubs name: {name}")
        slug = name.lower()
        other_name = seen_slugs.get(slug)
        if other_name is not None:
            die(
                f"duplicate mesh_hubs name after lowercase: "
                f"{name} conflicts with {other_name}"
            )
        seen_names.add(name)
        seen_slugs[slug] = name

        access_only = load_bool(raw.get(CONFIG_KEY_ACCESS_ONLY), f"{where}.access_only")
        listen_ip = normalize_listen_ip(
            raw.get(CONFIG_KEY_LISTEN_IP),
            f"{where}.listen_ip",
        )
        if not listen_ip:
            die(f"{where}.listen_ip must be a non-empty IPv4 address")
        other_name = seen_listen_ips.get(listen_ip)
        if other_name is not None:
            die(
                f"duplicate mesh_hubs.listen_ip {listen_ip}: "
                f"{name} conflicts with {other_name}"
            )
        seen_listen_ips[listen_ip] = name
        access_endpoints[name] = listen_ip

        if access_only:
            # Access-only entries provide public endpoints for access services,
            # but they are not real mesh hubs and do not consume infra AWG ports.
            continue

        require_linux_iface_name(
            f"{name}Out",
            f"{where}.name generated mesh outbound interface",
        )

        hubs.append(
            MeshHub(
                name=name,
                listen_ip=listen_ip,
                port_range=infra_awg_port_range(),
            )
        )

    return sorted(hubs, key=lambda h: h.name), dict(sorted(access_endpoints.items()))


def load_exit_hubs(raw_cfg: dict[str, object]) -> list[ExitHub]:
    hubs: list[ExitHub] = []
    seen_names: set[str] = set()
    seen_slugs: dict[str, str] = {}
    seen_listen_ips: dict[str, str] = {}

    raw_list = raw_cfg.get(CONFIG_KEY_EXIT_HUBS, [])
    if not isinstance(raw_list, list):
        die("config key 'exit_hubs' must be a list")

    for raw in raw_list:
        if not isinstance(raw, dict):
            die("each exit_hubs entry must be an object")

        name = raw.get(CONFIG_KEY_NAME)
        if not isinstance(name, str) or not name:
            die("exit_hubs.name must be a non-empty string")
        require_exit_hub_name(name, f"exit_hubs[{name}].name")
        require_linux_iface_name(
            exit_out_iface_name(name),
            f"exit_hubs[{name}].name generated exit outbound interface",
        )
        require_linux_iface_name(
            exit_in_iface_name(name),
            f"exit_hubs[{name}].name generated exit inbound interface",
        )
        require_linux_iface_name(
            router_exit_ipip_iface_name(name),
            f"exit_hubs[{name}].name generated exit IPIP UCI section",
        )
        require_generated_linux_iface_name(
            f"ipip-{router_exit_ipip_iface_name(name)}",
            f"exit_hubs[{name}].name generated Linux IPIP device",
        )
        where = f"exit_hubs[{name}]"
        require_known_keys(raw, where, EXIT_HUB_KEYS)

        if name in seen_names:
            die(f"duplicate exit_hubs name: {name}")
        slug = name.lower()
        other_name = seen_slugs.get(slug)
        if other_name is not None:
            die(
                f"duplicate exit_hubs directory name after lowercase: "
                f"{name} conflicts with {other_name}"
            )
        seen_names.add(name)
        seen_slugs[slug] = name

        listen_ip = normalize_listen_ip(
            raw.get(CONFIG_KEY_LISTEN_IP),
            f"{where}.listen_ip",
        )

        if listen_ip:
            other_name = seen_listen_ips.get(listen_ip)
            if other_name is not None:
                die(
                    f"duplicate exit_hubs.listen_ip {listen_ip}: "
                    f"{name} conflicts with {other_name}"
                )
            seen_listen_ips[listen_ip] = name

        exit_ip = normalize_optional_exit_ip(
            raw.get(CONFIG_KEY_EXIT_IP), f"{where}.exit_ip"
        )
        if exit_ip and not listen_ip:
            die(f"{where}.exit_ip requires listen_ip")

        hubs.append(
            ExitHub(
                name=name,
                node_ip="",
                listen_ip=listen_ip,
                exit_ip=exit_ip,
                announce="",
                port_range=infra_awg_port_range(),
            )
        )

    return sorted(hubs, key=lambda h: h.name)


def load_access_protocol(raw: object, where: str) -> str:
    if not isinstance(raw, str) or not raw:
        die(f"{where} must be one of: {', '.join(sorted(ACCESS_PROTOCOLS))}")
    value = raw.lower()
    if value not in ACCESS_PROTOCOLS:
        die(f"{where}: unknown access protocol: {raw}")
    return value


def load_access_policy(raw: object, where: str) -> str:
    if not isinstance(raw, str) or not raw:
        die(f"{where} must be one of: {', '.join(sorted(ACCESS_POLICIES))}")
    value = raw.lower()
    if value not in ACCESS_POLICIES:
        die(f"{where}: unknown access policy: {raw}")
    return value


def load_firewall_targets(
    raw: object, where: str, router_names: list[str]
) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, str):
        raw = [raw]

    if not isinstance(raw, list):
        die(f"{where} must be a string or a list of strings")

    targets: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            die(f"{where} must contain only non-empty strings")
        if item != "all" and item not in router_names:
            die(f"{where} references unknown router: {item}")
        if item not in targets:
            targets.append(item)

    return targets


def load_wifi_blocked_macs(raw: object, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()

    if isinstance(raw, str):
        raw = [raw]

    if not isinstance(raw, list):
        die(f"{where} must be a string or a list of MAC addresses")

    out: list[str] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, str) or not item:
            die(f"{where}[{idx}] must be a non-empty string")
        if not MAC_RE.fullmatch(item):
            die(f"{where}[{idx}] must be a MAC address like 02:00:00:00:00:01")

        mac = item.lower()
        if mac not in seen:
            seen.add(mac)
            out.append(mac)

    return tuple(out)


def load_wifi_config(raw: dict[str, object], where: str) -> dict[str, WifiConfig]:
    wifi_by_key: dict[str, WifiConfig] = {}

    for wifi_key in WIFI_CONFIG_KEYS:
        raw_wifi = raw.get(wifi_key)
        if raw_wifi is None:
            continue
        if not isinstance(raw_wifi, dict):
            die(f"{where}.{wifi_key} must be an object")

        ssid = raw_wifi.get(CONFIG_KEY_SSID)
        if not isinstance(ssid, str) or not ssid:
            die(f"{where}.{wifi_key}.ssid must be a non-empty string")

        key = raw_wifi.get(CONFIG_KEY_KEY)
        if not isinstance(key, str) or not key:
            die(f"{where}.{wifi_key}.key must be a non-empty string")

        blocked_macs = load_wifi_blocked_macs(
            raw_wifi.get(CONFIG_KEY_BLOCKED_MACS),
            f"{where}.{wifi_key}.{CONFIG_KEY_BLOCKED_MACS}",
        )

        wifi_by_key[wifi_key] = WifiConfig(
            ssid=ssid, key=key, blocked_macs=blocked_macs
        )

    return wifi_by_key


def expand_firewall_targets(cfg: ConfigData, allow: FirewallAllow) -> list[str]:
    if FIREWALL_TARGET_ALL not in allow.targets:
        return allow.targets

    return [name for name in cfg.router_names if name != allow.source_router]


def config_has_allow_to_router_all(cfg: ConfigData) -> bool:
    return any(
        allow.kind == FIREWALL_ALLOW_KIND_ROUTER
        and FIREWALL_TARGET_ALL in allow.targets
        for allow in cfg.firewall_allows
    )


def firewall_allow_rule_name(source_name: str, target_name: str, kind: str) -> str:
    suffix = "Router" if kind == FIREWALL_ALLOW_KIND_ROUTER else "Lan"
    return f"Allow-{source_name}-To-{target_name}-{suffix}"


def mesh_firewall_rule_name(_hub_name: str, target_name: str) -> str:
    return f"Allow-Mesh-{target_name}"


def config_network_item(text: str, where: str) -> tuple[str, ipaddress.IPv4Network]:
    try:
        return where, ipaddress.IPv4Network(text, strict=True)
    except ValueError as e:
        die(f"{where} is not a valid IPv4 network: {e}")


def validate_config_networks_do_not_overlap(
    routers: list[RouterDef],
    access: dict[str, list[AccessGroup]],
) -> None:
    items: list[tuple[str, ipaddress.IPv4Network]] = []

    for router in routers:
        items.append(
            config_network_item(router.subnet, f"routers[{router.name}].subnet")
        )

    for router_name, groups in access.items():
        for group in groups:
            subnet = f"{group.subnet}.0/{ACCESS_SUBNET_CIDR}"
            items.append(
                config_network_item(
                    subnet,
                    f"access[{router_name}][{group.name}].subnet",
                )
            )

    for where, subnet in (
        ("INFRA_LINK_POOL", INFRA_LINK_POOL),
        ("EXIT_ANNOUNCE_SUPERNET4", EXIT_ANNOUNCE_SUPERNET4),
        ("EXIT_NODE_SUPERNET4", EXIT_NODE_SUPERNET4),
    ):
        items.append(config_network_item(subnet, where))

    for left_idx, (left_where, left_net) in enumerate(items):
        for right_where, right_net in items[left_idx + 1 :]:
            if left_net.overlaps(right_net):
                die(
                    "IPv4 subnets must not overlap: "
                    f"{left_where}={left_net} overlaps {right_where}={right_net}"
                )


def build_config_data(raw_cfg: dict[str, object]) -> ConfigData:
    openwrt_version = normalize_openwrt_version(
        raw_cfg.get(CONFIG_KEY_OPENWRT_VERSION),
        "config.openwrt_version",
    )
    packages = load_config_packages(raw_cfg)
    device_profiles = load_device_profiles(raw_cfg)
    routers = load_routers(raw_cfg, device_profiles)
    router_by_name = {r.name: r for r in routers}
    router_names = [r.name for r in routers]

    main_router = raw_cfg.get(CONFIG_KEY_MAIN_ROUTER)
    if not isinstance(main_router, str) or not main_router:
        die("config.main_router must be a non-empty router name")
    if main_router not in router_by_name:
        die(f"config.main_router references unknown router: {main_router}")

    mesh_hubs, access_endpoints = load_mesh_hubs_and_access_endpoints(raw_cfg)
    for hub_name in access_endpoints:
        if hub_name not in router_by_name:
            die(f"mesh_hubs references unknown router: {hub_name}")
    mesh_hubs_by_name = {h.name: h for h in mesh_hubs}

    exit_hubs_raw = load_exit_hubs(raw_cfg)
    exit_hubs_by_name_raw = {h.name: h for h in exit_hubs_raw}
    exit_order_groups = load_exit_order_groups(
        raw_cfg.get(CONFIG_KEY_EXIT_ORDER),
        "config.exit_order",
        exit_hubs_by_name_raw,
        require_all=True,
    )
    exit_hubs = assign_generated_exit_announces(exit_hubs_raw, exit_order_groups)
    validate_exit_announce_set(exit_hubs)
    exit_hubs_by_name = {h.name: h for h in exit_hubs}
    exit_order = [name for group in exit_order_groups for name in group]
    exit_order_by_router: dict[str, list[str]] = {}
    exit_direct = load_exit_direct_config()

    access: dict[str, list[AccessGroup]] = {name: [] for name in router_names}
    firewall_allows: list[FirewallAllow] = []
    wifi: dict[str, dict[str, WifiConfig]] = {name: {} for name in router_names}

    raw_access = raw_cfg.get(CONFIG_KEY_ACCESS, {})
    if not isinstance(raw_access, dict):
        die("config key 'access' must be an object")

    raw_routers = raw_cfg.get(CONFIG_KEY_ROUTERS, [])
    if not isinstance(raw_routers, list):
        die("config key 'routers' must be a list")

    for raw in raw_routers:
        if not isinstance(raw, dict):
            die("each router entry must be an object")
        require_known_keys(
            raw, f"routers[{raw.get(CONFIG_KEY_NAME, '?')}]", ROUTER_KEYS
        )
        router_name = str(raw[CONFIG_KEY_NAME])
        router = router_by_name[router_name]
        router_exit_order = load_exit_order_names(
            raw.get(CONFIG_KEY_EXIT_ORDER),
            f"routers[{router_name}].exit_order",
            exit_hubs_by_name,
            require_all=False,
        )
        if router_exit_order:
            exit_order_by_router[router_name] = router_exit_order
        wifi[router_name] = load_wifi_config(raw, f"routers[{router_name}]")
        for key, kind in (
            (CONFIG_KEY_ALLOW_TO_ROUTER, FIREWALL_ALLOW_KIND_ROUTER),
            (CONFIG_KEY_ALLOW_TO_LAN, FIREWALL_ALLOW_KIND_LAN),
        ):
            targets = load_firewall_targets(
                raw.get(key),
                f"routers[{router_name}].{key}",
                router_names,
            )
            if targets:
                firewall_allows.append(
                    FirewallAllow(
                        source_name=router_name,
                        source_router=router_name,
                        source_subnet=router.subnet,
                        targets=targets,
                        kind=kind,
                    )
                )

    for router_name, groups in raw_access.items():
        if router_name not in router_by_name:
            die(f"access references unknown router: {router_name}")
        if not isinstance(groups, list):
            die(f"access[{router_name}] must be a list")

        router = router_by_name[router_name]
        seen_access_names: set[str] = set()
        seen_access_ports: set[int] = set()

        for idx, raw in enumerate(groups, start=1):
            if not isinstance(raw, dict):
                die(f"access[{router_name}][{idx}] must be an object")
            require_known_keys(
                raw,
                f"access[{router_name}][{raw.get(CONFIG_KEY_NAME, idx)}]",
                ACCESS_KEYS,
            )

            iface_name = raw.get(CONFIG_KEY_NAME)
            where = f"access[{router_name}][{idx}]"
            if not isinstance(iface_name, str) or not iface_name:
                die(f"{where}.name must be a non-empty string")
            require_linux_iface_name(iface_name, f"{where}.name")
            if iface_name in seen_access_names:
                die(f"duplicate access name on {router_name}: {iface_name}")
            seen_access_names.add(iface_name)

            protocol = load_access_protocol(
                raw.get(CONFIG_KEY_PROTOCOL), f"{where}.protocol"
            )
            policy = load_access_policy(raw.get(CONFIG_KEY_POLICY), f"{where}.policy")
            awg: AwgOptions | None = None
            if protocol == PROTOCOL_AMNEZIAWG:
                awg = load_awg_options(raw.get(CONFIG_KEY_AWG), where)
            elif raw.get(CONFIG_KEY_AWG) is not None:
                die(f"{where}.awg is only valid when protocol is amneziawg")

            port = raw.get(CONFIG_KEY_PORT)
            if not isinstance(port, int) or port < PORT_MIN or port > PORT_MAX:
                die(
                    f"access[{router_name}][{idx}].port must be an integer "
                    f"in {PORT_MIN}..{PORT_MAX}"
                )
            if port in seen_access_ports:
                die(f"duplicate access port on {router_name}: {port}")
            seen_access_ports.add(port)
            infra_ports = infra_awg_port_range()
            if infra_ports.start <= port <= infra_ports.end:
                die(
                    f"{where}.port conflicts with infra AWG port range "
                    f"{infra_ports}: {port}"
                )

            users_raw = raw.get(CONFIG_KEY_USERS)
            if not isinstance(users_raw, list):
                die(f"access[{router_name}][{idx}].users must be a list")
            users = []
            seen_users: set[str] = set()
            for user in users_raw:
                if not isinstance(user, str) or not user:
                    die(
                        f"access[{router_name}][{idx}].users must contain non-empty strings"
                    )
                require_file_identifier(user, f"access[{router_name}][{idx}].users")
                if user in seen_users:
                    die(f"duplicate access user on {router_name}/{iface_name}: {user}")
                seen_users.add(user)
                users.append(user)

            access_subnet = normalize_ipv4_subnet_24_prefix(
                raw.get(CONFIG_KEY_SUBNET), f"access[{router_name}][{idx}].subnet"
            )

            access[router_name].append(
                AccessGroup(
                    router_name=router_name,
                    name=iface_name,
                    protocol=protocol,
                    policy=policy,
                    subnet=access_subnet,
                    port=port,
                    users=users,
                    awg=awg,
                )
            )

            for key, kind in (
                (CONFIG_KEY_ALLOW_TO_ROUTER, FIREWALL_ALLOW_KIND_ROUTER),
                (CONFIG_KEY_ALLOW_TO_LAN, FIREWALL_ALLOW_KIND_LAN),
            ):
                targets = load_firewall_targets(
                    raw.get(key),
                    f"access[{router_name}][{idx}].{key}",
                    router_names,
                )
                if targets:
                    firewall_allows.append(
                        FirewallAllow(
                            source_name=iface_name,
                            source_router=router_name,
                            source_subnet=f"{access_subnet}.0/{ACCESS_SUBNET_CIDR}",
                            targets=targets,
                            kind=kind,
                        )
                    )

    for router_name, groups in access.items():
        if groups and router_name not in access_endpoints:
            die(
                f"access router {router_name}: cannot determine public endpoint; "
                f"add mesh_hubs entry with listen_ip, or use access_only=true"
            )

    validate_router_package_policy(routers, packages, access)
    validate_config_networks_do_not_overlap(routers, access)

    return ConfigData(
        routers=routers,
        router_by_name=router_by_name,
        router_names=router_names,
        openwrt_version=openwrt_version,
        main_router=main_router,
        packages=packages,
        device_profiles=device_profiles,
        mesh_hubs=mesh_hubs,
        mesh_hubs_by_name=mesh_hubs_by_name,
        access_endpoints=access_endpoints,
        exit_hubs=exit_hubs,
        exit_hubs_by_name=exit_hubs_by_name,
        exit_order=exit_order,
        exit_order_by_router=exit_order_by_router,
        exit_direct=exit_direct,
        access=access,
        firewall_allows=firewall_allows,
        wifi=wifi,
    )


def router_or_die(cfg: ConfigData, name: str) -> RouterDef:
    try:
        return cfg.router_by_name[name]
    except KeyError:
        die(f"unknown router: {name}")


def lan_subnet_prefix(cfg: ConfigData, router_name: str) -> str:
    return router_or_die(cfg, router_name).lan_prefix


def server_exit_subnet(cfg: ConfigData) -> str:
    router_nets = [
        ipaddress.ip_network(router.subnet, strict=True) for router in cfg.routers
    ]
    if not router_nets:
        die("cannot build server EXIT_SUBNETS: no routers configured")

    for private_net_text in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        private_net = ipaddress.ip_network(private_net_text)
        if all(net.subnet_of(private_net) for net in router_nets):
            return str(private_net)

    supernet = router_nets[0]
    while not all(net.subnet_of(supernet) for net in router_nets):
        if supernet.prefixlen == 0:
            break
        supernet = supernet.supernet()

    return str(supernet)


def server_exit_subnets(cfg: ConfigData) -> str:
    # NAT/guard only real routed client/source prefixes. 10.255.0.0/16 is
    # underlay infrastructure and must not be NATed by exit servers anymore.
    return server_exit_subnet(cfg)


def router_dir(cfg: ConfigData, name: str) -> Path:
    return ROUTERS_ROOT / router_or_die(cfg, name).slug


def router_path(cfg: ConfigData, name: str, kind: str) -> Path:
    return router_dir(cfg, name) / REL[kind]


def router_openvpn_root(cfg: ConfigData, router: str) -> Path:
    return router_path(cfg, router, "openvpn")


def router_openvpn_iface_dir(cfg: ConfigData, router: str, iface_name: str) -> Path:
    return router_openvpn_root(cfg, router) / iface_name


def router_openvpn_ca_dir(cfg: ConfigData, router: str, iface_name: str) -> Path:
    return router_openvpn_iface_dir(cfg, router, iface_name) / "ca"


def router_openvpn_server_conf_path(
    cfg: ConfigData, router: str, iface_name: str
) -> Path:
    return router_openvpn_iface_dir(cfg, router, iface_name) / "server.ovpn"


def router_openvpn_clients_dir(cfg: ConfigData, router: str, iface_name: str) -> Path:
    return router_openvpn_iface_dir(cfg, router, iface_name) / "clients"


def router_wireguard_root(cfg: ConfigData, router: str) -> Path:
    return router_path(cfg, router, "wireguard")


def router_wireguard_iface_dir(cfg: ConfigData, router: str, iface_name: str) -> Path:
    return router_wireguard_root(cfg, router) / iface_name


def router_wireguard_clients_dir(cfg: ConfigData, router: str, iface_name: str) -> Path:
    return router_wireguard_iface_dir(cfg, router, iface_name) / "clients"


def server_dir_name(exit: str) -> str:
    return exit.lower()


def server_exit_dir(exit: str) -> Path:
    return SERVER_ROOT / server_dir_name(exit)


def server_path(exit: str, *parts: str) -> Path:
    return server_exit_dir(exit).joinpath(*parts)


def server_amneziawg_dir(exit: str) -> Path:
    return server_path(exit, "etc", "amnezia", "amneziawg")


def server_client_conf_path(exit: str, client_alias: str) -> Path:
    return server_amneziawg_dir(exit) / f"{client_alias}.conf"


def server_babeld_slug(exit: str) -> str:
    return exit.lower()


def server_babeld_conf_basename(exit: str) -> str:
    return f"babel{server_babeld_slug(exit)}.conf"


def server_babeld_conf_path(exit: str) -> Path:
    return server_path(exit, "etc", server_babeld_conf_basename(exit))


def server_babeld_conf_remote_path(exit: str) -> str:
    return f"{SERVER_BABELD_CONF_PREFIX}{server_babeld_slug(exit)}{SERVER_BABELD_CONF_SUFFIX}"


def split_uci_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append("".join(current))
            current = []

    for line in lines:
        stripped = line.strip()

        if line.startswith("config "):
            flush()
            current = [line]
            continue

        if stripped == FIREWALL_MARKER:
            flush()
            blocks.append(line)
            continue

        if current:
            current.append(line)
        else:
            blocks.append(line)

    flush()
    return blocks


def parse_uci_block(block: str) -> dict[str, object]:
    lines = block.splitlines()
    if not lines:
        return {}

    first = lines[0]
    m = re.match(r"^config\s+(\S+)\s+'([^']+)'\s*$", first)
    if m:
        cfg_type, cfg_name = m.group(1), m.group(2)
    else:
        m = re.match(r"^config\s+(\S+)\s*$", first)
        if not m:
            return {}
        cfg_type, cfg_name = m.group(1), m.group(1)

    options: dict[str, str] = {}
    lists: dict[str, list[str]] = {}

    for line in lines[1:]:
        m = re.match(r"^\s*option\s+(\S+)\s+'([^']*)'\s*$", line)
        if m:
            options[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^\s*list\s+(\S+)\s+'([^']*)'\s*$", line)
        if m:
            lists.setdefault(m.group(1), []).append(m.group(2))

    return {
        "type": cfg_type,
        "name": cfg_name,
        "options": options,
        "lists": lists,
        "raw": block,
    }


def normalize_uci(text: str) -> str:
    blocks = [b.strip("\n") for b in split_uci_blocks(text) if b.strip("\n")]
    return "" if not blocks else "\n" + "\n\n".join(blocks) + "\n"


def uci_block(
    kind: str,
    name: str | None = None,
    *,
    options: dict[str, str] | None = None,
    lists: dict[str, list[str]] | None = None,
) -> str:
    lines = [f"config {kind}" + (f" '{name}'" if name else "")]
    for k, v in (options or {}).items():
        lines.append(f"    option {k} '{v}'")
    for k, vals in (lists or {}).items():
        for v in vals:
            lines.append(f"    list {k} '{v}'")
    return "\n".join(lines)


def current_mesh_exit_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    names: set[str] = mesh_iface_names_for_router(cfg, router_name)

    for hub in cfg.exit_hubs:
        names.add(exit_out_iface_name(hub.name))
        names.add(exit_in_iface_name(hub.name))
        names.add(router_exit_ipip_iface_name(hub.name))

    return names


def managed_mesh_exit_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return current_mesh_exit_ifaces(cfg, router_name)


def is_managed_network(
    parsed: dict[str, object],
    mesh_exit_ifaces: set[str] | None = None,
) -> bool:
    typ = str(parsed.get("type", ""))
    name = str(parsed.get("name", ""))
    mesh_exit_ifaces = mesh_exit_ifaces or set()

    # Current mesh/exit generated sections.
    if typ == "interface" and name in mesh_exit_ifaces:
        return True
    if name in {f"amneziawg_{iface}" for iface in mesh_exit_ifaces} | {
        f"wireguard_{iface}" for iface in mesh_exit_ifaces
    }:
        return True

    return False


def is_managed_access(parsed: dict[str, object], access_names: set[str]) -> bool:
    typ = str(parsed.get("type", ""))
    name = str(parsed.get("name", ""))

    if typ == "interface" and name in access_names:
        return True

    if typ.startswith("wireguard_") and typ == name:
        iface = typ.removeprefix("wireguard_")
        if iface in access_names:
            return True

    if typ.startswith("amneziawg_") and typ == name:
        iface = typ.removeprefix("amneziawg_")
        if iface in access_names:
            return True

    return False


def find_access_peer_block(
    cfg_by_name: dict[str, dict[str, object]],
    iface_name: str,
    user_name: str,
    protocol: str = PROTOCOL_WIREGUARD,
) -> dict[str, object] | None:
    prefix = (
        PROTOCOL_AMNEZIAWG if protocol == PROTOCOL_AMNEZIAWG else PROTOCOL_WIREGUARD
    )
    want_type = f"{prefix}_{iface_name}"
    want_desc = f"{user_name}.conf"

    for block in cfg_by_name.values():
        if block.get("type") != want_type:
            continue
        if block.get("options", {}).get("description") == want_desc:
            return block

    return None


def split_text_by_marker(text: str, path: Path) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == FIREWALL_MARKER:
            return "".join(lines[:i]), "".join(lines[i:])
    die(f"marker not found in {path}: {FIREWALL_MARKER}")


def filter_preserved_before_marker(text_before_marker: str, keep) -> str:
    out: list[str] = []
    for block in split_uci_blocks(text_before_marker):
        parsed = parse_uci_block(block)
        if not parsed:
            out.append(block)
            continue
        if keep(parsed):
            out.append(block)
    joined = "".join(out).rstrip()
    return joined + "\n" if joined else ""


def parse_network_part(cfg: ConfigData, router: str) -> dict[str, dict[str, object]]:
    path = router_path(cfg, router, "network")
    if not path.exists():
        die(f"missing file: {path}")

    out: dict[str, dict[str, object]] = {}
    counter = 0
    for block in split_uci_blocks(read(path)):
        parsed = parse_uci_block(block)
        if parsed:
            key = str(parsed["name"])
            if key in out:
                counter += 1
                key = f"{key}#{counter}"
            out[key] = parsed
    return out


def load_existing_network_cfgs(
    cfg: ConfigData,
) -> dict[str, dict[str, dict[str, object]]]:
    return {router: parse_network_part(cfg, router) for router in cfg.router_names}


def get_interface_private_key(
    cfg_by_name: dict[str, dict[str, object]],
    iface: str,
) -> str | None:
    for block in cfg_by_name.values():
        if block.get("type") == "interface" and block.get("name") == iface:
            return block["options"].get("private_key")
    return None


def get_interface_option(
    cfg_by_name: dict[str, dict[str, object]],
    iface: str,
    option_name: str,
) -> str | None:
    for block in cfg_by_name.values():
        if block.get("type") == "interface" and block.get("name") == iface:
            return block["options"].get(option_name)
    return None


def parse_existing_tunnel_conf(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    text = read(path)
    m = PRIVATE_KEY_RE.search(text)
    priv = m.group(1) if m else None
    return priv, (public_key_from_private(priv) if priv else None)


X25519_FIELD_SIZE = 2**255 - 19
X25519_BASE_POINT = 9


def clamp_x25519_private_key(raw: bytes) -> bytes:
    if len(raw) != 32:
        die("WireGuard private key must decode to 32 bytes")

    key = bytearray(raw)
    key[0] &= 248
    key[31] &= 127
    key[31] |= 64
    return bytes(key)


def decode_wireguard_key(value: str, where: str) -> bytes:
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except Exception as e:
        die(f"{where}: invalid base64 WireGuard/AmneziaWG key: {e}")

    if len(raw) != 32:
        die(f"{where}: WireGuard/AmneziaWG key must decode to 32 bytes")

    return raw


def x25519_public_key(private_key: bytes) -> bytes:
    scalar = clamp_x25519_private_key(private_key)
    x1 = X25519_BASE_POINT
    x2 = 1
    z2 = 0
    x3 = x1
    z3 = 1
    swap = 0

    def cswap(bit: int, left: int, right: int) -> tuple[int, int]:
        mask = -bit
        dummy = mask & (left ^ right)
        return left ^ dummy, right ^ dummy

    for bit_index in range(254, -1, -1):
        bit = (scalar[bit_index // 8] >> (bit_index & 7)) & 1
        swap ^= bit
        x2, x3 = cswap(swap, x2, x3)
        z2, z3 = cswap(swap, z2, z3)
        swap = bit

        a = (x2 + z2) % X25519_FIELD_SIZE
        aa = (a * a) % X25519_FIELD_SIZE
        b = (x2 - z2) % X25519_FIELD_SIZE
        bb = (b * b) % X25519_FIELD_SIZE
        e = (aa - bb) % X25519_FIELD_SIZE
        c = (x3 + z3) % X25519_FIELD_SIZE
        d = (x3 - z3) % X25519_FIELD_SIZE
        da = (d * a) % X25519_FIELD_SIZE
        cb = (c * b) % X25519_FIELD_SIZE

        x3 = ((da + cb) ** 2) % X25519_FIELD_SIZE
        z3 = (x1 * ((da - cb) ** 2)) % X25519_FIELD_SIZE
        x2 = (aa * bb) % X25519_FIELD_SIZE
        z2 = (e * (aa + 121665 * e)) % X25519_FIELD_SIZE

    x2, x3 = cswap(swap, x2, x3)
    z2, z3 = cswap(swap, z2, z3)

    inverse = pow(z2, X25519_FIELD_SIZE - 2, X25519_FIELD_SIZE)
    return ((x2 * inverse) % X25519_FIELD_SIZE).to_bytes(32, "little")


def gen_private_key() -> str:
    raw = clamp_x25519_private_key(os.urandom(32))
    return base64.b64encode(raw).decode("ascii")


def public_key_from_private(private_key: str) -> str:
    raw = decode_wireguard_key(private_key, "WireGuard/AmneziaWG private key")
    public = x25519_public_key(raw)
    return base64.b64encode(public).decode("ascii")


def openssl_req_subject(cn: str) -> str:
    return f"/CN={cn}"


def local_ca_material(
    ca_dir: Path,
    days: int,
    force: bool,
) -> tuple[Path, Path]:
    ca_dir.mkdir(parents=True, exist_ok=True)

    ca_key = ca_dir / "ca.key"
    ca_pem = ca_dir / "ca.pem"
    ca_srl = ca_dir / "ca.srl"

    effective_force = force and str(ca_dir) not in FORCED_CA_ONCE
    if effective_force:
        FORCED_CA_ONCE.add(str(ca_dir))
        rm(ca_key)
        rm(ca_pem)
        rm(ca_srl)

    if not ca_key.exists():
        print(f"Creating {ca_key}")
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(ca_key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if not ca_pem.exists():
        print(f"Creating {ca_pem}")
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-key",
                str(ca_key),
                "-out",
                str(ca_pem),
                "-days",
                str(days),
                "-subj",
                openssl_req_subject(DEFAULT_CA_CN),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return ca_key, ca_pem


def generate_ed25519_cert_signed_by_ca(
    ca_key: Path,
    ca_pem: Path,
    cn: str,
    days: int,
) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(
        prefix=".cert-",
        dir=LOCAL_TEMP_ROOT,
    ) as td:
        tmp = Path(td)
        key = tmp / "cert.key"
        csr = tmp / "cert.csr"
        crt = tmp / "cert.pem"
        srl = tmp / "ca.srl"

        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-key",
                str(key),
                "-out",
                str(csr),
                "-subj",
                openssl_req_subject(cn),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca_pem),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-CAserial",
                str(srl),
                "-out",
                str(crt),
                "-days",
                str(days),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return read(key), read(crt)


def openvpn_client_cn(client_index_1based: int) -> str:
    return f"client{client_index_1based}"


def extract_inline_block(text: str, tag: str) -> str | None:
    pattern = re.compile(
        rf"(?ms)^[ \t]*<{re.escape(tag)}>\s*\n(?P<body>.*?)\n[ \t]*</{re.escape(tag)}>\s*$"
    )
    m = pattern.search(text)
    if not m:
        return None
    return m.group("body").strip() + "\n"


def compute_mesh_link_params(
    cfg: ConfigData, hub: MeshHub, target_name: str
) -> LinkParams:
    key = mesh_link_key(hub.name, target_name)
    keys = mesh_link_keys(cfg, hub)
    network = stable_infra_link_network_for(cfg, key, f"mesh {hub.name}->{target_name}")
    srv_ip4, cli_ip4 = link_network_addresses(network)

    return LinkParams(
        srv_ip4=srv_ip4,
        cli_ip4=cli_ip4,
        srv_ll=ipv4_to_link_local(srv_ip4),
        cli_ll=ipv4_to_link_local(cli_ip4),
        port=stable_port_for(
            hub.port_range,
            keys,
            key,
            f"mesh hub {hub.name} ports",
        ),
    )


def exit_out_iface_name(hub_name: str) -> str:
    return f"{hub_name}Out"


def exit_in_iface_name(hub_name: str) -> str:
    return f"{hub_name}In"


def mesh_server_iface_name_for_target(target_name: str) -> str:
    return f"{target_name}In"


def client_iface_name_for_target(
    cfg: ConfigData,
    target_name: str,
    hub_name: str,
) -> str:
    _ = cfg, target_name
    return f"{hub_name}Out"


def compute_exit_link_params(
    cfg: ConfigData, hub: ExitHub, router_name: str
) -> LinkParams:
    key = exit_link_key(hub.name, router_name)
    keys = exit_link_keys(cfg, hub)
    network = stable_infra_link_network_for(cfg, key, f"exit {hub.name}->{router_name}")
    srv_ip4, cli_ip4 = link_network_addresses(network)

    return LinkParams(
        srv_ip4=srv_ip4,
        cli_ip4=cli_ip4,
        srv_ll=ipv4_to_link_local(srv_ip4),
        cli_ll=ipv4_to_link_local(cli_ip4),
        port=stable_port_for(
            hub.port_range,
            keys,
            key,
            f"Exit hub {hub.name} ports",
        ),
    )


def exit_reverse_listen_port(cfg: ConfigData, hub: ExitHub, router_name: str) -> int:
    if router_name not in cfg.mesh_hubs_by_name:
        die(f"router {router_name} is not a public mesh hub")

    mesh_hub = cfg.mesh_hubs_by_name[router_name]
    mesh_reserved = set(
        stable_unique_values(
            mesh_link_keys(cfg, mesh_hub),
            start=mesh_hub.port_range.start,
            end=mesh_hub.port_range.end,
            purpose="port",
            where=f"mesh hub {mesh_hub.name} ports",
        ).values()
    )

    key = exit_reverse_link_key(hub.name, router_name)
    keys = [
        exit_reverse_link_key(exit_hub.name, router_name) for exit_hub in cfg.exit_hubs
    ]
    return stable_port_avoiding_for(
        hub.port_range,
        keys,
        key,
        f"router {router_name} reverse exit ports",
        mesh_reserved,
    )


def compute_exit_reverse_link_params(
    cfg: ConfigData, hub: ExitHub, router_name: str
) -> LinkParams:
    key = exit_reverse_link_key(hub.name, router_name)
    network = stable_exit_reverse_link_network_for(
        cfg, key, f"exit-reverse {hub.name}->{router_name}"
    )
    srv_ip4, cli_ip4 = link_network_addresses(network)

    return LinkParams(
        srv_ip4=srv_ip4,
        cli_ip4=cli_ip4,
        srv_ll=ipv4_to_link_local(srv_ip4),
        cli_ll=ipv4_to_link_local(cli_ip4),
        port=exit_reverse_listen_port(cfg, hub, router_name),
    )


def compute_exit_exit_link_params(
    cfg: ConfigData, left_hub: ExitHub, right_hub: ExitHub
) -> ExitExitLinkParams:
    left_name, right_name = exit_exit_link_pair_for_hubs(
        cfg, left_hub.name, right_hub.name
    )
    hubs_by_name = {left_hub.name: left_hub, right_hub.name: right_hub}
    left = hubs_by_name[left_name]
    right = hubs_by_name[right_name]

    key = exit_exit_link_key(left.name, right.name)
    network = stable_exit_exit_link_network_for(
        cfg, key, f"exit-exit {left.name}Out->{right.name}In"
    )
    left_ip4, right_ip4 = link_network_addresses(network)

    left_reserved_ports = set(
        stable_unique_values(
            exit_link_keys(cfg, left),
            start=left.port_range.start,
            end=left.port_range.end,
            purpose="port",
            where=f"Exit hub {left.name} ports",
        ).values()
    )
    right_reserved_ports = set(
        stable_unique_values(
            exit_link_keys(cfg, right),
            start=right.port_range.start,
            end=right.port_range.end,
            purpose="port",
            where=f"Exit hub {right.name} ports",
        ).values()
    )

    return ExitExitLinkParams(
        left_name=left.name,
        right_name=right.name,
        left_ip4=left_ip4,
        right_ip4=right_ip4,
        left_ll=ipv4_to_link_local(left_ip4),
        right_ll=ipv4_to_link_local(right_ip4),
        left_port=stable_port_avoiding_for(
            left.port_range,
            exit_exit_link_keys_for_hub(cfg, left),
            key,
            f"Exit hub {left.name} exit-exit ports",
            left_reserved_ports,
        ),
        right_port=stable_port_avoiding_for(
            right.port_range,
            exit_exit_link_keys_for_hub(cfg, right),
            key,
            f"Exit hub {right.name} exit-exit ports",
            right_reserved_ports,
        ),
    )


def anonymized_link_alias(kind: str, hub_name: str, router_name: str) -> str:
    # Keep server-side AWG interface/config names anonymous and stable.
    # Format: 8 hex chars, for example 3f8a91c2.
    payload = f"{kind}\0{hub_name}\0{router_name}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:ANON_LINK_ALIAS_HEX_LEN]


def build_exit_base_alias(cfg: ConfigData, hub_name: str, router_name: str) -> str:
    router_or_die(cfg, router_name)
    return anonymized_link_alias("exit", hub_name, router_name)


def build_exit_client_alias(cfg: ConfigData, hub_name: str, router_name: str) -> str:
    # Router/leaf/spine dials public exit (ExitOut on the router side), so the
    # exit-server-side AWG config is the listener/inbound side of that session.
    return f"{build_exit_base_alias(cfg, hub_name, router_name)}In"


def build_exit_reverse_base_alias(
    cfg: ConfigData, hub_name: str, router_name: str
) -> str:
    if router_name not in cfg.mesh_hubs_by_name:
        die(f"router {router_name} is not a public mesh hub")
    return anonymized_link_alias("exit-in", hub_name, router_name)


def build_exit_reverse_client_alias(
    cfg: ConfigData, hub_name: str, router_name: str
) -> str:
    # Exit dials public spine (ExitIn on the router side), so the exit-server
    # AWG config is the client/outbound side of that reverse session.
    return f"{build_exit_reverse_base_alias(cfg, hub_name, router_name)}Out"


def build_exit_exit_base_alias(
    cfg: ConfigData, client_name: str, server_name: str
) -> str:
    client, server = exit_exit_pair_names(client_name, server_name)
    if client not in cfg.exit_hubs_by_name or server not in cfg.exit_hubs_by_name:
        die(f"unknown exit-exit pair: {client_name}<->{server_name}")
    return anonymized_link_alias("exit-exit", client, server)


def build_exit_exit_alias(cfg: ConfigData, local_name: str, peer_name: str) -> str:
    client_name, server_name = exit_exit_link_pair_for_hubs(cfg, local_name, peer_name)
    base = build_exit_exit_base_alias(cfg, client_name, server_name)
    if local_name == client_name:
        return f"{base}Out"
    if local_name == server_name:
        return f"{base}In"
    die(f"bad exit-exit alias mapping: {local_name}<->{peer_name}")


def build_mesh_client_alias(cfg: ConfigData, hub_name: str, router_name: str) -> str:
    router_or_die(cfg, router_name)
    return anonymized_link_alias("mesh", hub_name, router_name)


def is_under(relpath: Path, parent: Path) -> bool:
    try:
        relpath.relative_to(parent)
        return True
    except ValueError:
        return False
