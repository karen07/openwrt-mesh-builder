#!/usr/bin/env python3
from .awg_model import infra_awg_port_range, load_awg_options
from .config_dhcp_model import load_dhcp_config
from .config_exit_model import (
    assign_generated_exit_announces,
    load_exit_direct_config,
    load_exit_order_groups,
    load_exit_order_names,
    load_router_exit_route,
    load_router_routing_rules,
    validate_exit_announce_set,
)
from .config_loaders import (
    load_access_policy,
    load_access_protocol,
    load_config_packages,
    load_device_profiles,
    load_exit_hubs,
    load_firewall_targets,
    load_mesh_hubs_and_access_endpoints,
    load_pppoe_config,
    load_routers,
    load_wifi_config,
)
from .config_model import (
    AccessGroup,
    AwgOptions,
    ConfigData,
    FirewallAllow,
    PppoeConfig,
    RouterExitRoute,
    RoutingRule,
    WifiConfig,
)
from .config_schema import (
    ACCESS_KEYS,
    FIREWALL_ALLOW_KIND_LAN,
    FIREWALL_ALLOW_KIND_ROUTER,
    ROUTER_KEYS,
    normalize_openwrt_version,
    require_known_keys,
)
from .default import (
    ACCESS_SUBNET_CIDR,
    CONFIG_KEY_ACCESS,
    CONFIG_KEY_ALLOW_TO_LAN,
    CONFIG_KEY_ALLOW_TO_ROUTER,
    CONFIG_KEY_AWG,
    CONFIG_KEY_DHCP_HOSTS,
    CONFIG_KEY_EXIT_ORDER,
    CONFIG_KEY_EXIT_ROUTE,
    CONFIG_KEY_MAIN_ROUTER,
    CONFIG_KEY_NAME,
    CONFIG_KEY_OPENWRT_VERSION,
    CONFIG_KEY_POLICY,
    CONFIG_KEY_PORT,
    CONFIG_KEY_PROTOCOL,
    CONFIG_KEY_ROUTERS,
    CONFIG_KEY_ROUTING_RULES,
    CONFIG_KEY_SUBNET,
    CONFIG_KEY_USERS,
    PORT_MAX,
    PORT_MIN,
    PROTOCOL_AMNEZIAWG,
)
from .identifiers import require_file_identifier, require_linux_iface_name
from .net_model import (
    normalize_ipv4_subnet_24_prefix,
    validate_config_networks_do_not_overlap,
)
from .package_model import validate_router_package_policy
from .process import die


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
    routing_rules_by_router: dict[str, list[RoutingRule]] = {}
    exit_routes_by_router: dict[str, RouterExitRoute] = {}
    exit_direct = load_exit_direct_config()

    access: dict[str, list[AccessGroup]] = {name: [] for name in router_names}
    firewall_allows: list[FirewallAllow] = []
    wifi: dict[str, dict[str, WifiConfig]] = {name: {} for name in router_names}
    pppoe: dict[str, PppoeConfig] = {}
    dhcp = {}

    raw_access: dict[str, object] = {}

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
        if CONFIG_KEY_ACCESS in raw:
            raw_access[router_name] = raw[CONFIG_KEY_ACCESS]
        router_exit_order = load_exit_order_names(
            raw.get(CONFIG_KEY_EXIT_ORDER),
            f"routers[{router_name}].exit_order",
            exit_hubs_by_name,
            require_all=False,
        )
        if router_exit_order:
            exit_order_by_router[router_name] = router_exit_order
        router_routing_rules = load_router_routing_rules(
            raw.get(CONFIG_KEY_ROUTING_RULES),
            f"routers[{router_name}].routing_rules",
            router=router,
            exit_hubs_by_name=exit_hubs_by_name,
        )
        if router_routing_rules:
            routing_rules_by_router[router_name] = router_routing_rules
        exit_routes_by_router[router_name] = load_router_exit_route(
            raw.get(CONFIG_KEY_EXIT_ROUTE),
            f"routers[{router_name}].exit_route",
            exit_hubs_by_name=exit_hubs_by_name,
        )
        router_where = f"routers[{router_name}]"
        wifi[router_name] = load_wifi_config(raw, router_where)
        dhcp[router_name] = load_dhcp_config(
            raw.get(CONFIG_KEY_DHCP_HOSTS, []),
            router,
            router_where,
        )
        router_pppoe = load_pppoe_config(raw, router_where)
        if router_pppoe is not None:
            pppoe[router_name] = router_pppoe
        for key, kind in (
            (CONFIG_KEY_ALLOW_TO_ROUTER, FIREWALL_ALLOW_KIND_ROUTER),
            (CONFIG_KEY_ALLOW_TO_LAN, FIREWALL_ALLOW_KIND_LAN),
        ):
            where = f"routers[{router_name}].{key}"
            targets = load_firewall_targets(
                raw.get(key),
                where,
                router_names,
            )
            if router_name in targets:
                die(
                    f"{where} cannot target its own router {router_name}; "
                    "local access is controlled by the local firewall zone policy"
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
        if not isinstance(groups, list):
            die(f"routers[{router_name}].access must be a list")

        router = router_by_name[router_name]
        seen_access_names: set[str] = set()
        seen_access_ports: set[int] = set()

        for idx, raw in enumerate(groups, start=1):
            if not isinstance(raw, dict):
                die(f"routers[{router_name}].access[{idx}] must be an object")
            require_known_keys(
                raw,
                f"routers[{router_name}].access[{raw.get(CONFIG_KEY_NAME, idx)}]",
                ACCESS_KEYS,
            )

            iface_name = raw.get(CONFIG_KEY_NAME)
            where = f"routers[{router_name}].access[{idx}]"
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
                awg = load_awg_options(
                    raw.get(CONFIG_KEY_AWG),
                    where,
                    auto_key=f"access:{router_name}:{iface_name}",
                )
            elif raw.get(CONFIG_KEY_AWG) is not None:
                die(f"{where}.awg is only valid when protocol is amneziawg")

            port = raw.get(CONFIG_KEY_PORT)
            if not isinstance(port, int) or port < PORT_MIN or port > PORT_MAX:
                die(
                    f"routers[{router_name}].access[{idx}].port must be an integer "
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
                die(f"routers[{router_name}].access[{idx}].users must be a list")
            users = []
            seen_users: set[str] = set()
            for user in users_raw:
                if not isinstance(user, str) or not user:
                    die(
                        f"routers[{router_name}].access[{idx}].users must contain non-empty strings"
                    )
                require_file_identifier(
                    user, f"routers[{router_name}].access[{idx}].users"
                )
                if user in seen_users:
                    die(f"duplicate access user on {router_name}/{iface_name}: {user}")
                seen_users.add(user)
                users.append(user)

            access_subnet = normalize_ipv4_subnet_24_prefix(
                raw.get(CONFIG_KEY_SUBNET),
                f"routers[{router_name}].access[{idx}].subnet",
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
                target_where = f"routers[{router_name}].access[{idx}].{key}"
                targets = load_firewall_targets(
                    raw.get(key),
                    target_where,
                    router_names,
                )
                if router_name in targets:
                    die(
                        f"{target_where} cannot target its own router {router_name}; "
                        "local access is controlled by the access firewall zone policy"
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
        routing_rules_by_router=routing_rules_by_router,
        exit_routes_by_router=exit_routes_by_router,
        exit_direct=exit_direct,
        access=access,
        firewall_allows=firewall_allows,
        wifi=wifi,
        pppoe=pppoe,
        dhcp=dhcp,
    )
