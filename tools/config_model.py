#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from dataclasses import dataclass
from pathlib import Path

try:
    from .default import ROUTER_HOSTNAME_PREFIX, ROUTER_SSH_PREFIX, ROUTERS_ROOT
except ImportError:
    from default import ROUTER_HOSTNAME_PREFIX, ROUTER_SSH_PREFIX, ROUTERS_ROOT


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
