#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import ipaddress
import re

try:
    from .config_model import AccessGroup, ExitHub, RouterDef
    from .default import (
        ACCESS_SUBNET_CIDR,
        EXIT_ANNOUNCE_PREFIXLEN,
        EXIT_ANNOUNCE_SUPERNET4,
        EXIT_NODE_PREFIXLEN,
        EXIT_NODE_SUPERNET4,
        INFRA_LINK_POOL,
        IPV4_LINK_LOCAL_PREFIXLEN,
        IPV4_OCTET_COUNT,
        IPV4_OCTET_MAX,
        IPV4_OCTET_MIN,
        P2P_LINK_PREFIXLEN,
    )
    from .identifiers import CANONICAL_IPV4_RE
    from .process import die
    from .stable_model import stable_unique_values
except ImportError:
    from config_model import AccessGroup, ExitHub, RouterDef  # type: ignore
    from default import (  # type: ignore
        ACCESS_SUBNET_CIDR,
        EXIT_ANNOUNCE_PREFIXLEN,
        EXIT_ANNOUNCE_SUPERNET4,
        EXIT_NODE_PREFIXLEN,
        EXIT_NODE_SUPERNET4,
        INFRA_LINK_POOL,
        IPV4_LINK_LOCAL_PREFIXLEN,
        IPV4_OCTET_COUNT,
        IPV4_OCTET_MAX,
        IPV4_OCTET_MIN,
        P2P_LINK_PREFIXLEN,
    )
    from identifiers import CANONICAL_IPV4_RE  # type: ignore
    from process import die  # type: ignore
    from stable_model import stable_unique_values  # type: ignore


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
