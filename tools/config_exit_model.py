#!/usr/bin/env python3
import ipaddress
import re

from .config_model import (
    ConfigData,
    ExitDirectConfig,
    ExitHub,
    RouterDef,
    RouterExitRoute,
    RoutingRule,
)
from .config_schema import validate_exit_order_shape
from .default import (
    CONFIG_KEY_EXIT,
    CONFIG_KEY_MODE,
    CONFIG_KEY_SRC_IP,
    EXIT_DIRECT_ASNS,
    EXIT_DIRECT_COUNTRIES,
    EXIT_DIRECT_STATIC_IPSETS,
    EXIT_POLICY_BASE,
    ROUTING_MODE_AUTO,
    ROUTING_MODE_DIRECT,
    ROUTING_MODES,
)
from .net_model import (
    exit_announce_network,
    generated_exit_announce_network,
    generated_exit_node_ip,
)
from .process import die


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


def load_router_routing_rules(
    value: object,
    where: str,
    *,
    router: RouterDef,
    exit_hubs_by_name: dict[str, ExitHub],
) -> list[RoutingRule]:
    if value is None:
        return []
    if not isinstance(value, list):
        die(f"{where} must be a list")

    router_net = ipaddress.IPv4Network(router.subnet, strict=True)
    rules: list[RoutingRule] = []
    seen_sources: set[str] = set()

    for idx, raw in enumerate(value, start=1):
        rule_where = f"{where}[{idx}]"
        if not isinstance(raw, dict):
            die(f"{rule_where} must be an object")

        src_value = raw.get(CONFIG_KEY_SRC_IP)
        if not isinstance(src_value, str) or not src_value.strip():
            die(f"{rule_where}.src_ip must be a non-empty IPv4 address or /32")
        try:
            src_net = ipaddress.IPv4Network(src_value.strip(), strict=True)
        except ValueError as e:
            die(f"{rule_where}.src_ip must be an IPv4 address or strict /32: {e}")
        if src_net.prefixlen != 32:
            die(
                f"{rule_where}.src_ip must identify exactly one device (/32): "
                f"{src_net}"
            )
        if not src_net.subnet_of(router_net):
            die(
                f"{rule_where}.src_ip {src_net} is outside router subnet "
                f"{router_net}"
            )
        src_ip = str(src_net)
        if src_ip in seen_sources:
            die(f"{where}: duplicate src_ip: {src_ip}")
        seen_sources.add(src_ip)

        mode = raw.get(CONFIG_KEY_MODE)
        if not isinstance(mode, str) or mode not in ROUTING_MODES:
            die(
                f"{rule_where}.mode must be one of: "
                f"{', '.join(sorted(ROUTING_MODES))}"
            )

        exit_name: str | None = None
        if mode in {ROUTING_MODE_DIRECT, ROUTING_MODE_AUTO}:
            if CONFIG_KEY_EXIT in raw:
                die(f"{rule_where}.exit is not allowed for mode {mode}")
        else:
            exit_value = raw.get(CONFIG_KEY_EXIT)
            if not isinstance(exit_value, str) or not exit_value:
                die(f"{rule_where}.exit must be a non-empty exit hub name")
            if exit_value not in exit_hubs_by_name:
                die(f"{rule_where}.exit references unknown exit hub: {exit_value}")
            exit_name = exit_value

        rules.append(RoutingRule(src_ip=src_ip, mode=mode, exit_name=exit_name))

    return rules


def load_router_exit_route(
    value: object,
    where: str,
    *,
    exit_hubs_by_name: dict[str, ExitHub],
) -> RouterExitRoute:
    """Read the global EXIT policy only from the declarative router config."""
    if value is None:
        return RouterExitRoute("AUTO", None, ())
    if not isinstance(value, dict):
        die(f"{where} must be an object")
    allowed = {CONFIG_KEY_MODE, CONFIG_KEY_EXIT, "auto_exit"}
    extra = sorted(set(value) - allowed)
    if extra:
        die(f"{where}: unknown config key(s): {', '.join(extra)}")
    mode = value.get(CONFIG_KEY_MODE)
    modes = {
        "DIRECT",
        "AUTO",
        "SPLIT_FAIL_OPEN",
        "SPLIT_FAIL_CLOSED",
        "EXIT_FAIL_OPEN",
        "EXIT_FAIL_CLOSED",
    }
    if not isinstance(mode, str) or mode not in modes:
        die(f"{where}.mode must be one of: {', '.join(sorted(modes))}")
    fixed = {
        "SPLIT_FAIL_OPEN",
        "SPLIT_FAIL_CLOSED",
        "EXIT_FAIL_OPEN",
        "EXIT_FAIL_CLOSED",
    }
    exit_name = value.get(CONFIG_KEY_EXIT)
    if mode in fixed:
        if not isinstance(exit_name, str) or exit_name not in exit_hubs_by_name:
            die(f"{where}.exit must name a configured EXIT for mode {mode}")
    elif CONFIG_KEY_EXIT in value:
        die(f"{where}.exit is not allowed for mode {mode}")
    else:
        exit_name = None
    auto_exit = value.get("auto_exit", [])
    if not isinstance(auto_exit, list):
        die(f"{where}.auto_exit must be a list of EXIT names")
    if any(
        not isinstance(name, str) or name not in exit_hubs_by_name for name in auto_exit
    ):
        die(f"{where}.auto_exit contains an unknown EXIT name")
    if len(set(auto_exit)) != len(auto_exit):
        die(f"{where}.auto_exit contains duplicate EXIT names")
    return RouterExitRoute(mode, exit_name, tuple(auto_exit))


def routing_exit_policy_ids(cfg: ConfigData) -> dict[str, int]:
    # Stable globally: adding or removing device rules must not renumber tables.
    return {
        hub.name: EXIT_POLICY_BASE + idx + 1 for idx, hub in enumerate(cfg.exit_hubs)
    }


def router_required_exit_hubs(cfg: ConfigData, router_name: str) -> list[ExitHub]:
    # Every router must have an IPIP interface and a policy table for every exit.
    # A router-specific exit_order only controls AUTO preference, not which exits
    # are available to manual/global or per-device routing rules in LuCI.
    if router_name not in cfg.router_by_name:
        die(f"unknown router for exit route targets: {router_name}")
    return list(cfg.exit_hubs)


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
