#!/usr/bin/env python3
try:
    from .process import die
    from .default import *
    from .config_model import AccessGroup, ConfigData, FirewallAllow, WifiConfig
    from .config_schema import *
    from .config_exit_model import *
    from .config_firewall_model import *
    from .config_loaders import *
    from .identifiers import require_file_identifier, require_linux_iface_name
    from .package_model import validate_router_package_policy
    from .awg_model import infra_awg_port_range, load_awg_options
    from .net_model import (
        normalize_ipv4_subnet_24_prefix,
        validate_config_networks_do_not_overlap,
    )
except ImportError:
    from process import die  # type: ignore
    from default import *  # type: ignore
    from config_model import AccessGroup, ConfigData, FirewallAllow, WifiConfig  # type: ignore
    from config_schema import *  # type: ignore
    from config_exit_model import *  # type: ignore
    from config_firewall_model import *  # type: ignore
    from config_loaders import *  # type: ignore
    from identifiers import require_file_identifier, require_linux_iface_name  # type: ignore
    from package_model import validate_router_package_policy  # type: ignore
    from awg_model import infra_awg_port_range, load_awg_options  # type: ignore
    from net_model import (  # type: ignore
        normalize_ipv4_subnet_24_prefix,
        validate_config_networks_do_not_overlap,
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
