#!/usr/bin/env python3
import re

try:
    from .process import die
    from .default import *
    from .config_model import (
        AccessGroup,
        AwgOptions,
        DeviceProfile,
        ExitHub,
        MeshHub,
        RouterDef,
        WifiConfig,
    )
    from .identifiers import (
        require_device_profile_arch,
        require_device_profile_board,
        require_exit_hub_name,
        require_file_identifier,
        require_generated_linux_iface_name,
        require_linux_iface_name,
    )
    from .package_model import normalize_config_package_list
    from .awg_model import infra_awg_port_range, load_awg_options
    from .net_model import (
        normalize_ipv4_subnet_24_prefix,
        normalize_listen_ip,
        normalize_optional_exit_ip,
    )
    from .link_model import (
        exit_in_iface_name,
        exit_out_iface_name,
        mesh_server_iface_name_for_target,
    )
    from .config_schema import (
        ACCESS_POLICIES,
        ACCESS_PROTOCOLS,
        DEVICE_PROFILE_KEYS,
        EXIT_HUB_KEYS,
        MESH_HUB_KEYS,
        ROUTER_KEYS,
        WIFI_CONFIG_KEYS,
        require_known_keys,
        validate_config_known_keys,
    )
    from .config_exit_model import router_exit_ipip_iface_name
except ImportError:
    from process import die  # type: ignore
    from default import *  # type: ignore
    from config_model import (  # type: ignore
        AccessGroup,
        AwgOptions,
        DeviceProfile,
        ExitHub,
        MeshHub,
        RouterDef,
        WifiConfig,
    )
    from identifiers import (  # type: ignore
        require_device_profile_arch,
        require_device_profile_board,
        require_exit_hub_name,
        require_file_identifier,
        require_generated_linux_iface_name,
        require_linux_iface_name,
    )
    from package_model import normalize_config_package_list  # type: ignore
    from awg_model import infra_awg_port_range, load_awg_options  # type: ignore
    from net_model import (  # type: ignore
        normalize_ipv4_subnet_24_prefix,
        normalize_listen_ip,
        normalize_optional_exit_ip,
    )
    from link_model import (  # type: ignore
        exit_in_iface_name,
        exit_out_iface_name,
        mesh_server_iface_name_for_target,
    )
    from config_schema import (  # type: ignore
        ACCESS_POLICIES,
        ACCESS_PROTOCOLS,
        DEVICE_PROFILE_KEYS,
        EXIT_HUB_KEYS,
        MESH_HUB_KEYS,
        ROUTER_KEYS,
        WIFI_CONFIG_KEYS,
        require_known_keys,
        validate_config_known_keys,
    )
    from config_exit_model import router_exit_ipip_iface_name  # type: ignore

MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def load_bool(value: object, where: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        die(f"{where} must be a boolean")
    return value


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
