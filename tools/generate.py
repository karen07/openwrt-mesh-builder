#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import re
import shutil
from pathlib import Path

try:
    from .cli_common import urlopen_insecure
    from .common import *
except ImportError:
    from cli_common import urlopen_insecure
    from common import *


def mtu_uci_options() -> dict[str, str]:
    return {"mtu": str(TUNNEL_MTU)} if TUNNEL_MTU is not None else {}


def maybe_mtu_conf_line() -> list[str]:
    return [f"MTU = {TUNNEL_MTU}"] if TUNNEL_MTU is not None else []


def ipip_mtu_value() -> int | None:
    if IPIP_DEFAULT_MTU is not None:
        return IPIP_DEFAULT_MTU
    if TUNNEL_MTU is not None:
        return TUNNEL_MTU - 20
    return None


def ipip_mtu_uci_options() -> dict[str, str]:
    value = ipip_mtu_value()
    return {"mtu": str(value)} if value is not None else {}


def exit_hub_is_public(hub: ExitHub) -> bool:
    return bool(hub.listen_ip)


def router_is_public_mesh_hub(cfg: ConfigData, router_name: str) -> bool:
    return router_name in cfg.mesh_hubs_by_name


def router_exit_listen_port(cfg: ConfigData, hub: ExitHub, router_name: str) -> int:
    return exit_reverse_listen_port(cfg, hub, router_name)


def exit_reverse_firewall_rule_name(hub_name: str) -> str:
    return f"Allow-Exit-Reverse-{hub_name}"


# ============================================================
# ACCESS OPENVPN HELPERS
# ============================================================


def openvpn_server_cn(_router_name: str, _iface_name: str) -> str:
    return OPENVPN_SERVER_CN


def build_openvpn_access_interface_block(iface_name: str) -> str:
    return (
        uci_block(
            "interface",
            iface_name,
            options={
                "proto": "none",
                "device": iface_name,
            },
        )
        + "\n"
    )


def build_openvpn_server_conf(
    cfg: ConfigData,
    router_name: str,
    group: AccessGroup,
    ca_pem_text: str,
    cert_pem_text: str,
    key_pem_text: str,
) -> str:
    dns_ip = f"{lan_subnet_prefix(cfg, router_name)}.1"
    server_net = f"{group.subnet}.0"

    return (
        f"port {group.port}\n"
        f"proto {OPENVPN_SERVER_PROTO}\n\n"
        f"dev {group.name}\n"
        f"dev-type {OPENVPN_DEV_TYPE}\n\n"
        "dh none\n\n"
        f"topology {OPENVPN_TOPOLOGY}\n"
        f"server {server_net} 255.255.255.0\n\n"
        'push "redirect-gateway def1"\n'
        f'push "dhcp-option DNS {dns_ip}"\n\n'
        f"keepalive {OPENVPN_KEEPALIVE}\n"
        "persist-key\n"
        "persist-tun\n\n"
        f"data-ciphers {OPENVPN_DATA_CIPHERS}\n\n"
        f"user {OPENVPN_USER}\n"
        f"group {OPENVPN_GROUP}\n\n"
        f"verb {OPENVPN_VERB}\n"
        "mute-replay-warnings\n\n"
        "<ca>\n"
        f"{ca_pem_text.rstrip()}\n"
        "</ca>\n\n"
        "<cert>\n"
        f"{cert_pem_text.rstrip()}\n"
        "</cert>\n\n"
        "<key>\n"
        f"{key_pem_text.rstrip()}\n"
        "</key>\n"
    )


def build_openvpn_client_conf(
    remote_host: str,
    remote_port: int,
    ca_pem_text: str,
    cert_pem_text: str,
    key_pem_text: str,
) -> str:
    return (
        "client\n"
        f"dev {OPENVPN_DEV_TYPE}\n"
        f"proto {OPENVPN_CLIENT_PROTO}\n\n"
        f"remote {remote_host} {remote_port}\n\n"
        f"data-ciphers {OPENVPN_DATA_CIPHERS}\n\n"
        "resolv-retry infinite\n"
        "nobind\n"
        "persist-key\n"
        "persist-tun\n\n"
        f"verb {OPENVPN_VERB}\n"
        "mute-replay-warnings\n\n"
        "<ca>\n"
        f"{ca_pem_text.rstrip()}\n"
        "</ca>\n\n"
        "<cert>\n"
        f"{cert_pem_text.rstrip()}\n"
        "</cert>\n\n"
        "<key>\n"
        f"{key_pem_text.rstrip()}\n"
        "</key>\n"
    )


def router_public_host_for_access(cfg: ConfigData, router_name: str) -> str:
    endpoint = cfg.access_endpoints.get(router_name)
    if endpoint:
        return endpoint

    die(
        f"cannot determine public host for ACCESS on router {router_name}: "
        f"add a mesh_hubs entry with listen_ip, or use access_only=true"
    )


def ensure_openvpn_server_conf(
    cfg: ConfigData,
    router_name: str,
    group: AccessGroup,
    force: bool,
) -> None:
    iface_dir = router_openvpn_iface_dir(cfg, router_name, group.name)
    iface_dir.mkdir(parents=True, exist_ok=True)

    ca_dir = router_openvpn_ca_dir(cfg, router_name, group.name)
    ca_key, ca_pem = local_ca_material(
        ca_dir=ca_dir,
        days=DEFAULT_CERT_DAYS,
        force=force,
    )

    server_conf = router_openvpn_server_conf_path(cfg, router_name, group.name)
    existing_text = read(server_conf) if server_conf.exists() else ""

    existing_cert = extract_inline_block(existing_text, "cert")
    existing_key = extract_inline_block(existing_text, "key")

    if force or not existing_cert or not existing_key:
        server_key_text, server_cert_text = generate_ed25519_cert_signed_by_ca(
            ca_key=ca_key,
            ca_pem=ca_pem,
            cn=openvpn_server_cn(router_name, group.name),
            days=DEFAULT_CERT_DAYS,
        )
    else:
        server_cert_text = existing_cert
        server_key_text = existing_key

    write(
        server_conf,
        build_openvpn_server_conf(
            cfg=cfg,
            router_name=router_name,
            group=group,
            ca_pem_text=read(ca_pem),
            cert_pem_text=server_cert_text,
            key_pem_text=server_key_text,
        ),
    )


def ensure_openvpn_client_material(
    cfg: ConfigData,
    router_name: str,
    iface_name: str,
    user_name: str,
    client_index_1based: int,
    force: bool,
) -> tuple[str, str]:
    clients_dir = router_openvpn_clients_dir(cfg, router_name, iface_name)
    clients_dir.mkdir(parents=True, exist_ok=True)

    ovpn_path = clients_dir / f"{user_name}.ovpn"
    if ovpn_path.exists() and not force:
        existing = read(ovpn_path)
        existing_cert = extract_inline_block(existing, "cert")
        existing_key = extract_inline_block(existing, "key")
        if existing_cert and existing_key:
            return existing_key, existing_cert

    ca_dir = router_openvpn_ca_dir(cfg, router_name, iface_name)
    ca_key, ca_pem = local_ca_material(
        ca_dir=ca_dir,
        days=DEFAULT_CERT_DAYS,
        force=force,
    )

    return generate_ed25519_cert_signed_by_ca(
        ca_key=ca_key,
        ca_pem=ca_pem,
        cn=openvpn_client_cn(client_index_1based),
        days=DEFAULT_CERT_DAYS,
    )


def reconcile_router_openvpn_layout(
    cfg: ConfigData, router_name: str, iface_name: str
) -> None:
    iface_dir = router_openvpn_iface_dir(cfg, router_name, iface_name)
    iface_dir.mkdir(parents=True, exist_ok=True)
    (iface_dir / "ca").mkdir(parents=True, exist_ok=True)
    (iface_dir / "clients").mkdir(parents=True, exist_ok=True)


def reconcile_router_openvpn_dirs(
    cfg: ConfigData,
    router_name: str,
    keep_iface_names: set[str],
) -> None:
    root = router_openvpn_root(cfg, router_name)
    if not keep_iface_names:
        rm(root)
        return

    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir() and child.name not in keep_iface_names:
            rm(child)


def build_openvpn_uci_block(iface_name: str) -> str:
    return uci_block(
        PROTOCOL_OPENVPN,
        iface_name,
        options={
            "enabled": "1",
            "config": f"/etc/openvpn/{iface_name}/server.ovpn",
            "cd": f"/etc/openvpn/{iface_name}",
        },
    )


def update_openvpn_uci(
    cfg: ConfigData,
    router_name: str,
    groups: list[AccessGroup],
    extra_blocks: list[str] | None = None,
) -> None:
    path = router_path(cfg, router_name, "openvpn_uci")
    ovpn_groups = [g for g in groups if g.protocol == PROTOCOL_OPENVPN]
    blocks = [build_openvpn_uci_block(g.name) for g in ovpn_groups]
    blocks.extend(extra_blocks or [])

    if not blocks:
        rm(path)
        return

    lines: list[str] = ["package openvpn", ""]
    lines.append(
        "\n\n".join(block.strip() for block in blocks if block.strip()).rstrip()
    )
    lines.append("")

    write(path, "\n".join(lines).rstrip() + "\n")


def generate_openvpn_access(cfg: ConfigData, force: bool, verbose: bool) -> None:
    for router_name, groups in cfg.access.items():
        ovpn_groups = [g for g in groups if g.protocol == PROTOCOL_OPENVPN]
        keep_ifaces = {g.name for g in ovpn_groups}

        reconcile_router_openvpn_dirs(cfg, router_name, keep_ifaces)

        for group in ovpn_groups:
            reconcile_router_openvpn_layout(cfg, router_name, group.name)
            ensure_openvpn_server_conf(cfg, router_name, group, force)

            if verbose:
                print(
                    f"OPENVPN {router_name:<8} iface={group.name:<16} "
                    f"port={group.port:<5} subnet={group.subnet}.0/24"
                )


def generate_openvpn_client_files(cfg: ConfigData, force: bool, verbose: bool) -> None:
    for router_name, groups in cfg.access.items():
        for group in groups:
            if group.protocol != PROTOCOL_OPENVPN:
                continue

            reconcile_router_openvpn_layout(cfg, router_name, group.name)

            ca_pem = router_openvpn_ca_dir(cfg, router_name, group.name) / "ca.pem"
            remote_host = router_public_host_for_access(cfg, router_name)
            clients_dir = router_openvpn_clients_dir(cfg, router_name, group.name)
            clients_dir.mkdir(parents=True, exist_ok=True)

            keep_files = {f"{user}.ovpn" for user in group.users}
            for child in clients_dir.iterdir():
                if child.is_file() and child.name not in keep_files:
                    rm(child)

            for idx, user_name in enumerate(group.users, start=1):
                key_text, cert_text = ensure_openvpn_client_material(
                    cfg=cfg,
                    router_name=router_name,
                    iface_name=group.name,
                    user_name=user_name,
                    client_index_1based=idx,
                    force=force,
                )

                write(
                    clients_dir / f"{user_name}.ovpn",
                    build_openvpn_client_conf(
                        remote_host=remote_host,
                        remote_port=group.port,
                        ca_pem_text=read(ca_pem),
                        cert_pem_text=cert_text,
                        key_pem_text=key_text,
                    ),
                )

                if verbose:
                    print(
                        f"OPENVPN-CLIENT {router_name:<8} iface={group.name:<16} "
                        f"user={user_name:<12} remote={remote_host}:{group.port}"
                    )


# ============================================================
# ACCESS WG-LIKE CLIENT FILE HELPERS
# ============================================================


def build_wireguard_client_conf(
    client_private: str,
    client_ip4: str,
    server_public: str,
    remote_host: str,
    remote_port: int,
    dns_ip: str,
    awg: AwgOptions | None = None,
) -> str:
    awg_text = ""
    if awg is not None:
        awg_text = "".join(f"{line}\n" for line in awg_conf_lines(awg))

    return (
        "[Interface]\n"
        f"PrivateKey = {client_private}\n"
        f"Address = {client_ip4}\n"
        f"DNS = {dns_ip}\n"
        + (f"MTU = {TUNNEL_MTU}\n" if TUNNEL_MTU is not None else "")
        + awg_text
        + "\n"
        "[Peer]\n"
        f"PublicKey = {server_public}\n"
        f"Endpoint = {remote_host}:{remote_port}\n"
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}\n"
        f"PersistentKeepalive = {KEEPALIVE}\n"
    )


def reconcile_router_wireguard_dirs(
    cfg: ConfigData,
    router_name: str,
    keep_iface_names: set[str],
) -> None:
    root = router_wireguard_root(cfg, router_name)

    if not keep_iface_names:
        rm(root)
        return

    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir() and child.name not in keep_iface_names:
            rm(child)


def generate_wireguard_client_files(
    cfg: ConfigData,
    states_by_router: dict[str, list[AccessPeerState]],
    verbose: bool,
) -> None:
    for router_name, states in states_by_router.items():
        access_ifaces = {st.iface for st in states}
        reconcile_router_wireguard_dirs(cfg, router_name, access_ifaces)

        states_by_iface: dict[str, list[AccessPeerState]] = {}
        for st in states:
            states_by_iface.setdefault(st.iface, []).append(st)

        for iface_name, iface_states in states_by_iface.items():
            iface_dir = router_wireguard_iface_dir(cfg, router_name, iface_name)
            clients_dir = router_wireguard_clients_dir(cfg, router_name, iface_name)
            clients_dir.mkdir(parents=True, exist_ok=True)

            keep_files = {f"{st.user_name}.conf" for st in iface_states}
            for child in clients_dir.iterdir():
                if child.is_file() and child.name not in keep_files:
                    rm(child)

            remote_host = router_public_host_for_access(cfg, router_name)
            dns_ip = f"{lan_subnet_prefix(cfg, router_name)}.1"

            for st in iface_states:
                write(
                    clients_dir / f"{st.user_name}.conf",
                    build_wireguard_client_conf(
                        client_private=st.client_private,
                        client_ip4=st.client_ip4,
                        server_public=st.server_public,
                        remote_host=remote_host,
                        remote_port=st.port,
                        dns_ip=dns_ip,
                        awg=st.awg,
                    ),
                )

                if verbose:
                    label = (
                        "AWG-CLIENT"
                        if st.protocol == PROTOCOL_AMNEZIAWG
                        else "WG-CLIENT"
                    )
                    print(
                        f"{label} {router_name:<8} iface={iface_name:<16} "
                        f"user={st.user_name:<12} remote={remote_host}:{st.port} "
                        f"dir={iface_dir}"
                    )


# ============================================================
# BOOTSTRAP HELPERS
# ============================================================


def build_subnet_hostname_block(router: RouterDef) -> str:
    return (
        "    # Set subnet and name\n"
        f"    uci -q set network.lan.ipaddr='{router.lan_ipaddr}'\n"
        f"    uci -q set system.@system[0].hostname='{router.hostname}'\n"
    )


def update_subnet_hostname_block(body: str, router: RouterDef) -> str:
    managed = build_subnet_hostname_block(router)

    pattern = re.compile(
        r"""(?ms)
        ^[ \t]*\#\s*Set\s+subnet\s+and\s+name[ \t]*\n
        (?:^[ \t]*uci\s+(?:-q\s+)?set\s+network\.lan\.ipaddr='[^']*'[ \t]*\n)?
        (?:^[ \t]*uci\s+(?:-q\s+)?set\s+system\.@system\[0\]\.hostname='[^']*'[ \t]*\n)?
        (?:^[ \t]*(?:true|:)[ \t]*;?[ \t]*\n)?
        """,
        re.X,
    )

    updated, count = pattern.subn(managed, body, count=1)
    if count:
        return updated

    return managed + body


def build_doh_source_addr_block(router: RouterDef) -> str:
    source_addr = ipv4_without_prefix(router.lan_ipaddr)
    return (
        "    # Set DoH source address\n"
        f"    uci -q set https-dns-proxy.config.source_addr='{source_addr}'\n"
        "\n"
    )


def update_doh_source_addr_block(body: str, router: RouterDef) -> str:
    managed = build_doh_source_addr_block(router)

    pattern = re.compile(
        r"""(?ms)
        ^[ \t]*\#\s*Set\s+DoH\s+source\s+address[ \t]*\n
        (?:^[ \t]*uci\s+(?:-q\s+)?set\s+
            https-dns-proxy\.config\.source_addr='[^']*'[ \t]*\n)?
        (?:^[ \t]*\n)*
        """,
        re.X,
    )

    updated, count = pattern.subn(managed, body, count=1)
    if count:
        return updated

    anchor = re.compile(
        r"(?ms)"
        r"(^[ \t]*\#\s*Set\s+subnet\s+and\s+name[ \t]*\n"
        r"^[ \t]*uci\s+(?:-q\s+)?set\s+network\.lan\.ipaddr='[^']*'[ \t]*\n"
        r"^[ \t]*uci\s+(?:-q\s+)?set\s+system\.@system\[0\]\.hostname='[^']*'[ \t]*\n)"
        r"(?:^[ \t]*\n)*"
    )

    updated, count = anchor.subn(r"\1\n" + managed, body, count=1)
    if count:
        return updated

    return managed + body


try:
    from .default import ROUTER_SECRET_MARKER
except ImportError:
    from default import ROUTER_SECRET_MARKER

SECRET_MARKER_RE = re.compile(
    rf"^{re.escape(ROUTER_SECRET_MARKER)}\s*\{{\s*([A-Za-z0-9_\-\s]+?)\s*\}}$",
    re.S,
)

WIFI_MANAGED_COMMENT_RE = re.compile(r"^\s*#\s*Set\s+Wi-Fi(?:\s+radio[01])?\s*$")

WIFI_MANAGED_UCI_RE = re.compile(
    r"^\s*uci\s+(?:-q\s+)?(?:set|delete|add_list)\s+"
    r"wireless\.(?:radio[01]|default_radio[01])(?:\.|\b)"
)

DANGLING_SECRET_CLOSE_RE = re.compile(r"^\s*\}'\s*$")


def wrap_secret_marker_for_shell(value: str, width: int = SHELL_SECRET_WRAP_COL) -> str:
    m = SECRET_MARKER_RE.fullmatch(value)
    if not m:
        return value

    payload = re.sub(r"\s+", "", m.group(1))
    lines = [payload[i : i + width] for i in range(0, len(payload), width)]
    return f"{ROUTER_SECRET_MARKER}\n{{\n" + "\n".join(lines) + "\n}"


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def shell_wifi_value(value: str) -> str:
    return shell_single_quote(wrap_secret_marker_for_shell(value))


def build_wifi_macfilter_lines(iface: str, blocked_macs: tuple[str, ...]) -> list[str]:
    lines = [
        f"    uci -q delete wireless.{iface}.macfilter",
        f"    uci -q delete wireless.{iface}.maclist",
    ]

    if blocked_macs:
        lines.append(f"    uci -q set wireless.{iface}.macfilter='deny'")
        for mac in blocked_macs:
            lines.append(
                f"    uci -q add_list wireless.{iface}.maclist={shell_single_quote(mac)}"
            )

    return lines


def build_wifi_radio_block(
    wifi_by_key: dict[str, WifiConfig],
    wifi_key: str,
    radio: str,
    iface: str,
) -> list[str]:
    lines = [f"    # Set Wi-Fi {radio}"]
    wifi = wifi_by_key.get(wifi_key)

    if wifi is None:
        lines.extend(
            [
                f"    uci -q set wireless.{radio}.disabled='1'",
                f"    uci -q set wireless.{iface}.disabled='1'",
            ]
        )
        lines.extend(build_wifi_macfilter_lines(iface, ()))
        return lines

    lines.extend(
        [
            f"    uci -q delete wireless.{radio}.disabled",
            f"    uci -q delete wireless.{iface}.disabled",
            f"    uci -q set wireless.{radio}.country='{WIFI_COUNTRY}'",
            f"    uci -q set wireless.{radio}.cell_density='{WIFI_CELL_DENSITY}'",
            f"    uci -q set wireless.{iface}.ssid={shell_wifi_value(wifi.ssid)}",
            f"    uci -q set wireless.{iface}.encryption='{WIFI_ENCRYPTION}'",
            f"    uci -q set wireless.{iface}.key={shell_wifi_value(wifi.key)}",
        ]
    )
    lines.extend(build_wifi_macfilter_lines(iface, wifi.blocked_macs))
    return lines


def build_wifi_block(cfg: ConfigData, router_name: str) -> str:
    lines: list[str] = []
    wifi_by_key = cfg.wifi.get(router_name, {})

    for wifi_key, (radio, iface) in WIFI_RADIO_BY_KEY.items():
        if lines:
            lines.append("")
        lines.extend(build_wifi_radio_block(wifi_by_key, wifi_key, radio, iface))

    return "\n".join(lines).rstrip() + "\n\n"


def router_has_openvpn_access(cfg: ConfigData, router_name: str) -> bool:
    return any(g.protocol == PROTOCOL_OPENVPN for g in cfg.access.get(router_name, []))


def build_openvpn_babeld_hotplug_block() -> str:
    return """    # Restart babeld when generated OpenVPN access interface comes up
    mkdir -p /etc/hotplug.d/iface
    cat >/etc/hotplug.d/iface/99-babeld-openvpn <<'EOF'
#!/bin/sh

[ "$ACTION" = ifup ] || exit 0
[ -n "$INTERFACE" ] || exit 0

enabled="$(uci -q get "openvpn.$INTERFACE.enabled")"
[ "$enabled" = "1" ] || exit 0

logger -t babeld "Restarting babeld due to OpenVPN ifup of $INTERFACE ($DEVICE)"
/etc/init.d/babeld restart
EOF
    chmod +x /etc/hotplug.d/iface/99-babeld-openvpn

"""


def remove_openvpn_babeld_hotplug_block(body: str) -> str:
    # Remove only the exact block that this generator writes.
    # If a user edits that hotplug snippet by hand, it stays above the marker
    # and show_unmanaged.py can report it as unmanaged instead of silently
    # hiding a broad comment-to-chmod range.
    return body.replace(build_openvpn_babeld_hotplug_block(), "")


def update_openvpn_babeld_hotplug_block(
    body: str,
    cfg: ConfigData,
    router_name: str,
) -> str:
    body = remove_openvpn_babeld_hotplug_block(body)

    if not router_has_openvpn_access(cfg, router_name):
        return body

    body = body.rstrip()
    if body:
        body += "\n\n"

    return body + build_openvpn_babeld_hotplug_block()


def line_text(line: str) -> str:
    return line.rstrip("\r\n")


def line_has_open_single_quote(line: str) -> bool:
    return line_text(line).count("'") % 2 == 1


def skip_managed_wifi_block(lines: list[str], start: int) -> int:
    i = start + 1
    in_single_quote = False

    while i < len(lines):
        text = line_text(lines[i])

        if in_single_quote:
            if line_has_open_single_quote(lines[i]):
                in_single_quote = False
            i += 1
            continue

        if not text.strip():
            i += 1
            continue

        if WIFI_MANAGED_COMMENT_RE.match(text):
            i += 1
            continue

        if WIFI_MANAGED_UCI_RE.match(text):
            in_single_quote = line_has_open_single_quote(lines[i])
            i += 1
            continue

        # Be forgiving when cleaning files produced by the older broken matcher:
        # a dangling closing marker line could be left before the next managed UCI line.
        if DANGLING_SECRET_CLOSE_RE.match(text):
            i += 1
            continue

        break

    return i


def remove_managed_wifi_blocks(body: str) -> str:
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    i = 0

    while i < len(lines):
        if WIFI_MANAGED_COMMENT_RE.match(line_text(lines[i])):
            i = skip_managed_wifi_block(lines, i)
            continue
        out.append(lines[i])
        i += 1

    return "".join(out)


def update_wifi_block(body: str, cfg: ConfigData, router_name: str) -> str:
    body = remove_managed_wifi_blocks(body)
    managed = build_wifi_block(cfg, router_name)

    anchor = re.compile(
        r"(?ms)"
        r"(^[ \t]*\#\s*Set\s+subnet\s+and\s+name[ \t]*\n"
        r"(?:^[ \t]*uci\s+(?:-q\s+)?set\s+network\.lan\.ipaddr='[^']*'[ \t]*\n)?"
        r"(?:^[ \t]*uci\s+(?:-q\s+)?set\s+system\.@system\[0\]\.hostname='[^']*'[ \t]*\n)?)"
        r"(?:^[ \t]*\n)*"
    )

    updated, count = anchor.subn(r"\1\n" + managed, body, count=1)
    if count:
        return updated

    return managed + body


def update_bootstrap(cfg: ConfigData, router_name: str) -> None:
    router = router_or_die(cfg, router_name)
    path = router_path(cfg, router_name, "bootstrap")
    text = read(path)

    m = re.search(r"(?ms)^customization\(\)\s*\{\n(?P<body>.*?)^\}[ \t]*$", text)
    if not m:
        die(f"{path}: customization() block not found or malformed")

    body = m.group("body")
    body = update_subnet_hostname_block(body, router)
    body = update_doh_source_addr_block(body, router)
    body = update_wifi_block(body, cfg, router_name)
    body = update_openvpn_babeld_hotplug_block(body, cfg, router_name)

    updated = text[: m.start("body")] + body + text[m.end("body") :]
    write(path, updated)


# ============================================================
# MESH HELPERS
# ============================================================


def build_mesh_material(
    hub_cfg: dict[str, dict[str, object]],
    target_cfg: dict[str, dict[str, object]],
    server_iface_name: str,
    client_iface_name: str,
    force: bool,
) -> KeyMaterial:
    if force:
        c_priv = gen_private_key()
        s_priv = gen_private_key()
        return KeyMaterial(
            c_priv,
            public_key_from_private(c_priv),
            s_priv,
            public_key_from_private(s_priv),
        )

    server_priv = get_interface_private_key(hub_cfg, server_iface_name)
    client_priv = get_interface_private_key(target_cfg, client_iface_name)

    if server_priv and client_priv:
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if server_priv and not client_priv:
        client_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if not server_priv and client_priv:
        server_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )

    client_priv = gen_private_key()
    server_priv = gen_private_key()
    return KeyMaterial(
        client_priv,
        public_key_from_private(client_priv),
        server_priv,
        public_key_from_private(server_priv),
    )


def build_mesh_server_block(state: MeshLinkState) -> str:
    iface = uci_block(
        "interface",
        state.server_iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": state.keys.server_private,
            "listen_port": str(state.link.port),
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(state.awg),
        },
        lists={"addresses": [state.link.srv_ip4, state.link.srv_ll]},
    )
    peer = uci_block(
        state.server_peer_section_name,
        None,
        options={
            "description": f"{state.server_iface_name}.conf",
            "public_key": state.keys.client_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": str(KEEPALIVE),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_mesh_client_block(state: MeshLinkState) -> str:
    endpoint_host, endpoint_port = peer_endpoint(
        listen_ip=state.hub.listen_ip,
        port=state.link.port,
    )

    iface = uci_block(
        "interface",
        state.client_iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": state.keys.client_private,
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(state.awg),
        },
        lists={"addresses": [state.link.cli_ip4, state.link.cli_ll]},
    )
    peer = uci_block(
        state.client_peer_section_name,
        None,
        options={
            "description": f"{state.client_iface_name}.conf",
            "public_key": state.keys.server_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": str(KEEPALIVE),
            "endpoint_host": endpoint_host,
            "endpoint_port": str(endpoint_port),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_mesh_state(
    cfg: ConfigData,
    existing_all: dict[str, dict[str, dict[str, object]]],
    force: bool,
    verbose: bool,
) -> tuple[
    dict[str, str],
    dict[str, list[str]],
    dict[str, list[MeshLinkState]],
]:
    network_blocks = {router: "" for router in cfg.router_names}
    mesh_ifaces = {router: [] for router in cfg.router_names}
    hub_states: dict[str, list[MeshLinkState]] = {h.name: [] for h in cfg.mesh_hubs}
    for hub_name, target_router in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        hub_cfg = existing_all[hub.name]
        target_cfg = existing_all[target_router]
        server_iface_name = mesh_server_iface_name_for_target(target_router)
        client_iface_name = client_iface_name_for_target(cfg, target_router, hub.name)

        state = MeshLinkState(
            hub=hub,
            target_router=target_router,
            client_alias=build_mesh_client_alias(cfg, hub.name, target_router),
            server_iface_name=server_iface_name,
            client_iface_name=client_iface_name,
            server_peer_section_name=f"amneziawg_{server_iface_name}",
            client_peer_section_name=f"amneziawg_{client_iface_name}",
            link=compute_mesh_link_params(cfg, hub, target_router),
            keys=build_mesh_material(
                hub_cfg,
                target_cfg,
                server_iface_name,
                client_iface_name,
                force,
            ),
            awg=awg_for_infra_link(mesh_link_key(hub.name, target_router)),
        )

        network_blocks[hub.name] += build_mesh_server_block(state)
        network_blocks[target_router] += build_mesh_client_block(state)
        hub_states[hub.name].append(state)
        mesh_ifaces[hub.name].append(server_iface_name)
        mesh_ifaces[target_router].append(client_iface_name)

        if verbose:
            print(
                f"MESH {hub.name:<8} -> {target_router:<10} "
                f"srv_port={state.link.port:<5} "
                f"cli_port={state.link.port:<5}"
            )

    for router in mesh_ifaces:
        mesh_ifaces[router] = sorted(set(mesh_ifaces[router]))
    return network_blocks, mesh_ifaces, hub_states


# ============================================================
# Exit HELPERS
# ============================================================


def build_material_for_exit(
    router_name: str,
    hub: ExitHub,
    client_alias: str,
    router_iface_name: str,
    router_cfg: dict[str, dict[str, object]],
    force: bool,
) -> KeyMaterial:
    _ = router_name
    if force:
        c_priv = gen_private_key()
        s_priv = gen_private_key()
        return KeyMaterial(
            c_priv,
            public_key_from_private(c_priv),
            s_priv,
            public_key_from_private(s_priv),
        )

    client_priv = get_interface_private_key(router_cfg, router_iface_name)
    server_conf = server_client_conf_path(hub.name, client_alias)
    server_priv, _ = parse_existing_tunnel_conf(server_conf)

    if client_priv and server_priv:
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if client_priv and not server_priv:
        server_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if not client_priv and server_priv:
        client_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )

    client_priv = gen_private_key()
    server_priv = gen_private_key()
    return KeyMaterial(
        client_priv,
        public_key_from_private(client_priv),
        server_priv,
        public_key_from_private(server_priv),
    )


def build_material_for_exit_reverse(
    hub: ExitHub,
    client_alias: str,
    router_iface_name: str,
    router_cfg: dict[str, dict[str, object]],
    force: bool,
) -> KeyMaterial:
    # For ExitXXIn, the OpenWrt side is the listener/server and the exit-side
    # .conf is the dialer/client. Keep the same KeyMaterial meaning:
    # client_* belongs to the exit-side .conf, server_* belongs to OpenWrt.
    if force:
        c_priv = gen_private_key()
        s_priv = gen_private_key()
        return KeyMaterial(
            c_priv,
            public_key_from_private(c_priv),
            s_priv,
            public_key_from_private(s_priv),
        )

    server_priv = get_interface_private_key(router_cfg, router_iface_name)

    server_conf = server_client_conf_path(hub.name, client_alias)
    client_priv, _ = parse_existing_tunnel_conf(server_conf)

    if client_priv and server_priv:
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if client_priv and not server_priv:
        server_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )
    if not client_priv and server_priv:
        client_priv = gen_private_key()
        return KeyMaterial(
            client_priv,
            public_key_from_private(client_priv),
            server_priv,
            public_key_from_private(server_priv),
        )

    client_priv = gen_private_key()
    server_priv = gen_private_key()
    return KeyMaterial(
        client_priv,
        public_key_from_private(client_priv),
        server_priv,
        public_key_from_private(server_priv),
    )


def build_exit_out_network_interface_block(
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    iface_name = exit_out_iface_name(hub.name)
    endpoint_host, endpoint_port = peer_endpoint(
        listen_ip=hub.listen_ip,
        port=link.port,
    )

    iface = uci_block(
        "interface",
        iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": keys.client_private,
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(awg),
        },
        lists={"addresses": [link.cli_ip4, link.cli_ll]},
    )
    peer = uci_block(
        f"amneziawg_{iface_name}",
        None,
        options={
            "description": f"{iface_name}.conf",
            "public_key": keys.server_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": str(KEEPALIVE),
            "endpoint_host": endpoint_host,
            "endpoint_port": str(endpoint_port),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_exit_in_network_interface_block(
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    iface_name = exit_in_iface_name(hub.name)
    iface = uci_block(
        "interface",
        iface_name,
        options={
            "proto": PROTOCOL_AMNEZIAWG,
            "private_key": keys.server_private,
            "listen_port": str(link.port),
            "defaultroute": "0",
            **mtu_uci_options(),
            **awg_uci_options(awg),
        },
        lists={"addresses": [link.srv_ip4, link.srv_ll]},
    )
    peer = uci_block(
        f"amneziawg_{iface_name}",
        None,
        options={
            "description": f"{iface_name}.conf",
            "public_key": keys.client_public,
            "route_allowed_ips": "1",
            "persistent_keepalive": str(KEEPALIVE),
        },
        lists={"allowed_ips": DEFAULT_ALLOWED_IPS},
    )
    return iface + "\n\n" + peer + "\n"


def build_exit_ipip_interface_block(
    cfg: ConfigData,
    router_name: str,
    hub: ExitHub,
) -> str:
    # Outer source is the router LAN gateway IP. It is already redistributed
    # by Babel, so the exit can route replies/control traffic back if needed.
    return (
        uci_block(
            "interface",
            router_exit_ipip_iface_name(hub.name),
            options={
                "proto": "ipip",
                "ipaddr": f"{lan_subnet_prefix(cfg, router_name)}.1",
                "peeraddr": exit_ipip_endpoint_ip(hub),
                "nohostroute": "1",
                **ipip_mtu_uci_options(),
            },
        )
        + "\n"
    )


def router_exit_order_hubs(cfg: ConfigData, router_name: str) -> list[ExitHub]:
    order = cfg.exit_order_by_router.get(router_name, []) or cfg.exit_order
    if not order:
        order = [hub.name for hub in cfg.exit_hubs]
    return [cfg.exit_hubs_by_name[name] for name in order]


def build_server_direct_conf(
    client_alias: str,
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    _ = client_alias, hub
    lines = [
        "[Interface]",
        f"PrivateKey = {keys.server_private}",
        f"Address = {link.srv_ip4}, {link.srv_ll}",
        f"ListenPort = {link.port}",
        *maybe_mtu_conf_line(),
        *awg_conf_lines(awg),
        "Table = off",
        "",
        "[Peer]",
        f"PublicKey = {keys.client_public}",
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}",
        f"PersistentKeepalive = {KEEPALIVE}",
    ]
    return "\n".join(lines) + "\n"


def build_server_reverse_conf(
    cfg: ConfigData,
    router_name: str,
    client_alias: str,
    hub: ExitHub,
    link: LinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    _ = client_alias, hub
    router_hub = cfg.mesh_hubs_by_name[router_name]
    endpoint_host, endpoint_port = peer_endpoint(
        listen_ip=router_hub.listen_ip,
        port=link.port,
    )
    lines = [
        "[Interface]",
        f"PrivateKey = {keys.client_private}",
        f"Address = {link.cli_ip4}, {link.cli_ll}",
        *maybe_mtu_conf_line(),
        *awg_conf_lines(awg),
        "Table = off",
        "",
        "[Peer]",
        f"PublicKey = {keys.server_public}",
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}",
        f"Endpoint = {endpoint_host}:{endpoint_port}",
        f"PersistentKeepalive = {KEEPALIVE}",
    ]
    return "\n".join(lines) + "\n"


def exit_exit_conf_path(cfg: ConfigData, exit_name: str, peer_name: str) -> Path:
    return server_client_conf_path(
        exit_name, build_exit_exit_alias(cfg, exit_name, peer_name)
    )


def build_material_for_exit_exit(
    cfg: ConfigData, left_hub: ExitHub, right_hub: ExitHub, force: bool
) -> KeyMaterial:
    left_name, right_name = exit_exit_link_pair_for_hubs(
        cfg, left_hub.name, right_hub.name
    )
    left_conf = exit_exit_conf_path(cfg, left_name, right_name)
    right_conf = exit_exit_conf_path(cfg, right_name, left_name)

    if force:
        left_priv = gen_private_key()
        right_priv = gen_private_key()
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )

    left_priv, _ = parse_existing_tunnel_conf(left_conf)
    right_priv, _ = parse_existing_tunnel_conf(right_conf)

    if left_priv and right_priv:
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )
    if left_priv and not right_priv:
        right_priv = gen_private_key()
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )
    if not left_priv and right_priv:
        left_priv = gen_private_key()
        return KeyMaterial(
            left_priv,
            public_key_from_private(left_priv),
            right_priv,
            public_key_from_private(right_priv),
        )

    left_priv = gen_private_key()
    right_priv = gen_private_key()
    return KeyMaterial(
        left_priv,
        public_key_from_private(left_priv),
        right_priv,
        public_key_from_private(right_priv),
    )


def build_exit_exit_server_conf(
    local_hub: ExitHub,
    peer_hub: ExitHub,
    link: ExitExitLinkParams,
    keys: KeyMaterial,
    awg: AwgOptions,
) -> str:
    if local_hub.name == link.left_name and peer_hub.name == link.right_name:
        local_private = keys.client_private
        local_ip4 = link.left_ip4
        local_ll = link.left_ll
        local_port = link.left_port
        peer_public = keys.server_public
        peer_port = link.right_port
    elif local_hub.name == link.right_name and peer_hub.name == link.left_name:
        local_private = keys.server_private
        local_ip4 = link.right_ip4
        local_ll = link.right_ll
        local_port = link.right_port
        peer_public = keys.client_public
        peer_port = link.left_port
    else:
        die(
            f"bad exit-exit local/peer mapping: "
            f"{local_hub.name}<->{peer_hub.name} for {link.left_name}<->{link.right_name}"
        )

    peer_lines = [
        "[Peer]",
        f"PublicKey = {peer_public}",
        f"AllowedIPs = {DEFAULT_ALLOWED_IPS_TEXT}",
    ]
    if exit_hub_is_public(peer_hub):
        endpoint_host, endpoint_port = peer_endpoint(
            listen_ip=peer_hub.listen_ip,
            port=peer_port,
        )
        peer_lines.append(f"Endpoint = {endpoint_host}:{endpoint_port}")
    peer_lines.append(f"PersistentKeepalive = {KEEPALIVE}")

    lines = [
        "[Interface]",
        f"PrivateKey = {local_private}",
        f"Address = {local_ip4}, {local_ll}",
        f"ListenPort = {local_port}",
        *maybe_mtu_conf_line(),
        *awg_conf_lines(awg),
        "Table = off",
        "",
        *peer_lines,
    ]
    return "\n".join(lines) + "\n"


def build_server_babeld_conf(
    hub: ExitHub,
    states: list[RouterExitState],
    exit_exit_aliases: list[str],
) -> str:
    _ = hub
    ifaces = sorted({st.client_alias for st in states} | set(exit_exit_aliases))
    lines = [
        f"interface {iface} type {BABELD_TUNNEL_TYPE} "
        f"hello-interval {BABELD_HELLO_INTERVAL} "
        f"update-interval {BABELD_UPDATE_INTERVAL}"
        for iface in ifaces
    ]
    lines += [
        "",
        "install allow",
        "",
        f"redistribute if {NODE_SERVER_IFACE} allow",
        f"redistribute if {IPIP_SERVER_IFACE} allow",
        "redistribute local deny",
        "",
    ]
    return "\n".join(lines)


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_server_env(
    cfg: ConfigData,
    hub: ExitHub,
    states: list[RouterExitState],
    exit_exit_aliases: list[str],
) -> str:
    service_names = sorted(
        {f"awg-quick@{st.client_alias}.service" for st in states}
        | {f"awg-quick@{alias}.service" for alias in exit_exit_aliases}
    )
    awg_services = " ".join(service_names)

    values = {
        "SERVER_NAME": hub.name,
        "NODE_ADDR4": exit_node_addr4(hub),
        "NODE_IFACE": NODE_SERVER_IFACE,
        "LISTEN_IP": hub.listen_ip,
        "EXIT_IP": hub.exit_ip,
        "IPIP_IFACE": IPIP_SERVER_IFACE,
        "IPIP_ADDR4": exit_ipip_endpoint_addr4(hub),
        **({"IPIP_MTU": str(ipip_mtu_value())} if ipip_mtu_value() is not None else {}),
        "EXIT_SUBNETS": server_exit_subnets(cfg),
        "IPSET_NAME": SERVER_ENV_IPSET_NAME,
        "IPSETS_DIR": RUNTIME_IPSETS_DIR,
        "STATIC_DIRECT_NAME": RUNTIME_DIRECT_STATIC_NAME,
        "OUT_DIRECT_NAME": RUNTIME_DIRECT_OUT_NAME,
        "DIRECT_COUNTRIES": " ".join(cfg.exit_direct.countries),
        "DIRECT_ASNS": " ".join(cfg.exit_direct.asns),
        "UPDATE_IPSETS_CURL_CONNECT_TIMEOUT": str(UPDATE_IPSETS_CURL_CONNECT_TIMEOUT),
        "UPDATE_IPSETS_CURL_MAX_TIME": str(UPDATE_IPSETS_CURL_MAX_TIME),
        "UPDATE_IPSETS_CURL_RETRY": str(UPDATE_IPSETS_CURL_RETRY),
        "AWG_SERVICES": awg_services,
        "BABELD_CONF": server_babeld_conf_remote_path(hub.name),
    }

    lines = [
        "# Generated by generate.py. Do not edit on the server.",
        "# Runtime settings consumed by /etc/awg-server.sh.",
    ]
    for key, value in values.items():
        lines.append(f"{key}={shell_quote(value)}")
    lines.append("")
    return "\n".join(lines)


def normalize_ipset_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for line in lines:
        item = line.strip()

        if not item or item.startswith("#"):
            continue

        if item in seen:
            continue

        seen.add(item)
        out.append(item)

    return out


def download_text_lines(url: str) -> list[str]:
    try:
        with urlopen_insecure(url, timeout=30) as response:
            text = response.read().decode("utf-8")
    except Exception as e:
        die(f"failed to download {url}: {e}")

    return [line for line in text.splitlines() if line and not line.startswith("#")]


def direct_country_url(country: str) -> str:
    return f"{URL_IPVERSE_RIR}/country/{country}/ipv4-aggregated.txt"


def direct_asn_url(asn: str) -> str:
    return f"{URL_IPVERSE_ASN}/as/{asn}/ipv4-aggregated.txt"


def direct_static_lines(cfg: ConfigData) -> list[str]:
    lines: list[str] = []

    lines.extend(LOCAL_DIRECT_IPSETS)
    lines.extend(cfg.exit_direct.subnets)

    for hub in cfg.mesh_hubs:
        lines.append(hub.listen_ip)

    for hub in cfg.exit_hubs:
        if hub.listen_ip:
            lines.append(hub.listen_ip)
        if hub.exit_ip:
            lines.append(hub.exit_ip)

    return normalize_ipset_lines(lines)


def direct_dynamic_lines(cfg: ConfigData) -> list[str]:
    lines: list[str] = []

    for country in cfg.exit_direct.countries:
        lines.extend(download_text_lines(direct_country_url(country)))

    for asn in cfg.exit_direct.asns:
        lines.extend(download_text_lines(direct_asn_url(asn)))

    return normalize_ipset_lines(lines)


def exit_route_env_key(name: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_]", "_", name).upper()
    if not key or key[0].isdigit():
        key = f"_{key}"
    return key


def build_runtime_env(cfg: ConfigData, router_name: str | None = None) -> str:
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

    values = {
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

    lines = [
        "# Generated by generate.py. Do not edit on the host.",
        "# Runtime settings consumed by /etc/scripts/*.sh.",
    ]
    lines.extend(f"{key}={shell_quote(value)}" for key, value in values.items())

    for hub in hubs:
        key = exit_route_env_key(hub.name)
        lines.append(
            f"EXIT_ROUTE_{key}_PREFIX={shell_quote(str(exit_announce_network(hub)))}"
        )

    lines.append("")
    return "\n".join(lines)


def write_ipsets_at(
    root: Path, cfg: ConfigData, router_name: str | None = None
) -> None:
    static_lines = direct_static_lines(cfg)
    dynamic_lines = direct_dynamic_lines(cfg)
    direct_lines = normalize_ipset_lines(static_lines + dynamic_lines)

    write(root / REL_DIRECT_STATIC_IPSET, "\n".join(static_lines) + "\n")
    write(root / REL_RUNTIME_ENV, build_runtime_env(cfg, router_name))
    write(root / REL_DIRECT_IPSET, "\n".join(direct_lines) + "\n")


def write_router_ipsets(cfg: ConfigData, router_name: str) -> None:
    write_ipsets_at(router_dir(cfg, router_name), cfg, router_name)


def write_server_ipsets(cfg: ConfigData, exit_name: str) -> None:
    static_lines = direct_static_lines(cfg)
    dynamic_lines = direct_dynamic_lines(cfg)
    direct_lines = normalize_ipset_lines(static_lines + dynamic_lines)

    write(
        server_path(exit_name, "etc", "ipsets", "direct-static.txt"),
        "\n".join(static_lines) + "\n",
    )
    write(
        server_path(exit_name, "etc", "ipsets", "direct.txt"),
        "\n".join(direct_lines) + "\n",
    )


def reconcile_server_dirs(keep_exit_names: set[str]) -> None:
    SERVER_ROOT.mkdir(parents=True, exist_ok=True)
    protected = {server_dir_name(name) for name in keep_exit_names}
    protected.add(SERVER_TEMPLATE_NAME)

    for child in SERVER_ROOT.iterdir():
        if child.is_dir() and child.name not in protected:
            rm(child)


def ensure_server_layout(exit_name: str) -> None:
    dst = server_exit_dir(exit_name)
    if not dst.exists():
        if not SERVER_TEMPLATE_DIR.is_dir():
            die(f"missing server example directory: {SERVER_TEMPLATE_DIR}")
        print(f"Creating {dst} from {SERVER_TEMPLATE_DIR}")
        shutil.copytree(SERVER_TEMPLATE_DIR, dst, copy_function=shutil.copy2)
    else:
        cp_tree(SERVER_TEMPLATE_DIR, dst)

    for p in (
        server_path(exit_name, "etc"),
        server_amneziawg_dir(exit_name),
        server_path(exit_name, "etc", "ipsets"),
        server_path(exit_name, "etc", "systemd", "system"),
    ):
        p.mkdir(parents=True, exist_ok=True)


def remove_stale_server_amneziawg_confs(exit_name: str, keep_aliases: set[str]) -> None:
    conf_dir = server_amneziawg_dir(exit_name)
    conf_dir.mkdir(parents=True, exist_ok=True)
    keep_files = {f"{alias}.conf" for alias in keep_aliases}

    for child in conf_dir.iterdir():
        if (
            child.is_file()
            and child.name.endswith(".conf")
            and child.name not in keep_files
        ):
            rm(child)


# ============================================================
# ACCESS HELPERS
# ============================================================


def build_access_interface_block(
    iface_name: str,
    protocol: str,
    awg: AwgOptions | None,
    server_private: str,
    server_ip4: str,
    port: int,
) -> str:
    options = {
        "proto": protocol,
        "private_key": server_private,
        "listen_port": str(port),
        "defaultroute": "0",
        **mtu_uci_options(),
    }
    if protocol == PROTOCOL_AMNEZIAWG:
        if awg is None:
            die(f"access {iface_name}: awg options are required for amneziawg")
        options.update(awg_uci_options(awg))

    return (
        uci_block(
            "interface",
            iface_name,
            options=options,
            lists={"addresses": [server_ip4]},
        )
        + "\n"
    )


def build_access_peer_block(state: AccessPeerState) -> str:
    prefix = (
        PROTOCOL_AMNEZIAWG
        if state.protocol == PROTOCOL_AMNEZIAWG
        else PROTOCOL_WIREGUARD
    )
    return (
        uci_block(
            f"{prefix}_{state.iface}",
            None,
            options={
                "public_key": state.client_public,
                "description": f"{state.user_name}.conf",
                "route_allowed_ips": "1",
                "persistent_keepalive": str(KEEPALIVE),
            },
            lists={"allowed_ips": [state.client_ip4]},
        )
        + "\n"
    )


def build_access_state(
    cfg: ConfigData,
    existing_all: dict[str, dict[str, dict[str, object]]],
    access_groups: dict[str, list[AccessGroup]],
    force: bool,
    verbose: bool,
) -> tuple[dict[str, str], dict[str, list[AccessPeerState]], set[str]]:
    network_blocks = {router: "" for router in access_groups}
    states_by_router: dict[str, list[AccessPeerState]] = {
        router: [] for router in access_groups
    }
    managed_names: set[str] = set()

    for router_name, groups in access_groups.items():
        cfg_by_name = existing_all[router_name]

        for group in groups:
            managed_names.add(group.name)

            if group.protocol == PROTOCOL_OPENVPN:
                network_blocks[router_name] += build_openvpn_access_interface_block(
                    group.name
                )
                if verbose:
                    print(
                        f"ACCESS {router_name:<8} {group.name:<12} "
                        f"name={group.name:<16} protocol=openvpn subnet={group.subnet}.0/24"
                    )
                continue

            server_ip4 = host_ip_in_prefix(
                group.subnet, ACCESS_SERVER_HOST, ACCESS_SUBNET_CIDR
            )

            existing_iface_priv = get_interface_private_key(cfg_by_name, group.name)
            if existing_iface_priv is not None and not force:
                server_priv = existing_iface_priv
            else:
                server_priv = gen_private_key()

            server_pub = public_key_from_private(server_priv)

            network_blocks[router_name] += build_access_interface_block(
                group.name,
                group.protocol,
                group.awg,
                server_priv,
                server_ip4,
                group.port,
            )

            for idx, user_name in enumerate(group.users):
                host = ACCESS_HOST_START + idx
                client_ip4 = host_ip_in_prefix(group.subnet, host, CLIENT_TUNNEL_CIDR)

                if force:
                    client_priv = gen_private_key()
                    client_pub = public_key_from_private(client_priv)
                else:
                    client_conf = (
                        router_wireguard_clients_dir(cfg, router_name, group.name)
                        / f"{user_name}.conf"
                    )
                    old_priv, old_pub_from_conf = parse_existing_tunnel_conf(
                        client_conf
                    )

                    peer_block = find_access_peer_block(
                        cfg_by_name, group.name, user_name, group.protocol
                    )
                    old_pub_from_uci = None
                    if peer_block:
                        old_pub_from_uci = peer_block.get("options", {}).get(
                            "public_key"
                        )

                    if old_priv:
                        client_priv = old_priv
                        client_pub = (
                            old_pub_from_uci
                            or old_pub_from_conf
                            or public_key_from_private(client_priv)
                        )
                    else:
                        client_priv = gen_private_key()
                        client_pub = public_key_from_private(client_priv)

                state = AccessPeerState(
                    router_name=router_name,
                    iface=group.name,
                    user_name=user_name,
                    client_ip4=client_ip4,
                    server_ip4=server_ip4,
                    subnet=group.subnet,
                    port=group.port,
                    protocol=group.protocol,
                    awg=group.awg,
                    client_private=client_priv,
                    client_public=client_pub,
                    server_private=server_priv,
                    server_public=server_pub,
                )

                network_blocks[router_name] += build_access_peer_block(state)
                states_by_router[router_name].append(state)

                if verbose:
                    print(
                        f"ACCESS {router_name:<8} {group.name:<12} "
                        f"protocol={group.protocol:<10} user={user_name:<12} ip={client_ip4}"
                    )

    return network_blocks, states_by_router, managed_names


# ============================================================
# FILE RENDER / UPDATE HELPERS
# ============================================================


def update_network_part(
    cfg: ConfigData,
    router_name: str,
    mesh_text: str,
    exit_text: str,
    ipip_text: str,
    access_text: str,
    access_names: set[str],
) -> None:
    path = router_path(cfg, router_name, "network")
    original = read(path)

    before_marker, marker_and_tail = split_text_by_marker(original, path)

    mesh_exit_names = managed_mesh_exit_ifaces(cfg, router_name)

    def keep_block(parsed: dict[str, object]) -> bool:
        if is_managed_network(parsed, mesh_exit_names):
            return False
        if is_managed_access(parsed, access_names):
            return False
        return True

    preserved_before = filter_preserved_before_marker(before_marker, keep_block)

    mesh_rendered = normalize_uci(mesh_text).strip("\n")
    exit_rendered = normalize_uci(exit_text).strip("\n")
    ipip_rendered = normalize_uci(ipip_text).strip("\n")
    access_rendered = normalize_uci(access_text).strip("\n")
    preserved_rendered = preserved_before.strip("\n")
    tail_rendered = marker_and_tail.rstrip("\n")

    parts: list[str] = []
    if access_rendered:
        parts.append(access_rendered)
    if mesh_rendered:
        parts.append(mesh_rendered)
    if exit_rendered:
        parts.append(exit_rendered)
    if ipip_rendered:
        parts.append(ipip_rendered)
    if preserved_rendered:
        parts.append(preserved_rendered)
    if tail_rendered:
        parts.append(tail_rendered)

    updated = "\n\n".join(parts).rstrip() + "\n" if parts else ""
    write(path, normalize_uci(updated))


def build_zone(
    name: str,
    ifaces: list[str],
    *,
    forward: str,
    masq: bool = False,
    mtu_fix: bool = False,
    input_policy: str = FIREWALL_TARGET_REJECT,
    output_policy: str = FIREWALL_TARGET_ACCEPT,
) -> str:
    options = {
        "name": name,
        "input": input_policy,
        "output": output_policy,
        "forward": forward,
    }
    if masq:
        options["masq"] = "1"
    if masq or mtu_fix:
        options["mtu_fix"] = "1"
    return uci_block("zone", None, options=options, lists={"network": ifaces})


def build_rule_allow_port_wan(name: str, port: int, proto: str) -> str:
    return uci_block(
        "rule",
        None,
        options={
            "name": name,
            "src": FIREWALL_ZONE_WAN,
            "dest_port": str(port),
            "target": FIREWALL_TARGET_ACCEPT,
            "proto": proto,
        },
    )


def build_rule_allow_mesh_src_ip(
    name: str,
    src_ip: str,
    dest_zone: str | None,
) -> str:
    options = {
        "name": name,
        "src": ZONE_MESH,
        "target": FIREWALL_TARGET_ACCEPT,
        "family": "ipv4",
        "proto": "all",
    }
    if dest_zone is not None:
        options["dest"] = dest_zone

    return uci_block(
        "rule",
        None,
        options=options,
        lists={"src_ip": [src_ip]},
    )


def build_rule_allow_dns_transit_access() -> str:
    return uci_block(
        "rule",
        None,
        options={
            "name": TRANSIT_ACCESS_DNS_RULE_NAME,
            "src": ZONE_TRANSIT_ACCESS,
            "dest_port": str(DNS_PORT),
            "target": FIREWALL_TARGET_ACCEPT,
        },
        lists={"proto": DNS_PROTOCOLS},
    )


def build_rule_allow_ssh_from_exit_to_router() -> str:
    return uci_block(
        "rule",
        None,
        options={
            "name": "Allow-SSH-From-Exit-To-Router",
            "src": ZONE_EXIT,
            "proto": TRANSPORT_TCP,
            "dest_port": "22",
            "target": FIREWALL_TARGET_ACCEPT,
        },
    )


def update_firewall_part(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
    exit_ipip_ifaces: list[str],
    access_groups_for_router: list[AccessGroup],
) -> None:
    path = router_path(cfg, router_name, "firewall")
    original = read(path)

    before_marker, marker_and_tail = split_text_by_marker(original, path)

    rule_names_to_manage: set[str] = {
        TRANSIT_ACCESS_DNS_RULE_NAME,
        "Allow-SSH-From-Exit-To-Router",
    }
    if router_name in cfg.mesh_hubs_by_name:
        rule_names_to_manage.add(FIREWALL_RULE_ALLOW_MESH)
        hub = cfg.mesh_hubs_by_name[router_name]
        for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
            rule_names_to_manage.add(mesh_firewall_rule_name(hub.name, target_name))
        for exit_hub in cfg.exit_hubs:
            rule_names_to_manage.add(exit_reverse_firewall_rule_name(exit_hub.name))

    for group in access_groups_for_router:
        rule_names_to_manage.add(f"Allow-{group.name}")

    for allow in cfg.firewall_allows:
        for target_name in expand_firewall_targets(cfg, allow):
            if target_name == router_name:
                rule_names_to_manage.add(
                    firewall_allow_rule_name(allow.source_name, target_name, allow.kind)
                )

    zone_names_to_manage = set(MANAGED_FIREWALL_ZONES)

    def keep_block(parsed: dict[str, object]) -> bool:
        typ = str(parsed.get("type", ""))
        options = parsed.get("options", {})
        zone_name = str(options.get("name", ""))

        if typ == "zone" and zone_name in zone_names_to_manage:
            return False
        if typ == "zone" and zone_name == ZONE_EXIT_IPIP:
            return False
        if typ == "rule":
            rule_name = str(options.get("name", ""))
            if rule_name in rule_names_to_manage:
                return False
        return True

    preserved_before = filter_preserved_before_marker(before_marker, keep_block)

    blocks: list[str] = []

    if mesh_ifaces:
        blocks.append(
            build_zone(
                ZONE_MESH,
                mesh_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ifaces:
        blocks.append(
            build_zone(
                ZONE_EXIT,
                exit_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ipip_ifaces:
        blocks.append(
            build_zone(
                ZONE_EXIT_IPIP,
                exit_ipip_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ifaces and not config_has_allow_to_router_all(cfg):
        blocks.append(build_rule_allow_ssh_from_exit_to_router().strip())

    trusted_access_ifaces = sorted(
        {g.name for g in access_groups_for_router if g.policy == ACCESS_POLICY_TRUSTED}
    )
    transit_access_ifaces = sorted(
        {g.name for g in access_groups_for_router if g.policy == ACCESS_POLICY_TRANSIT}
    )

    if trusted_access_ifaces:
        blocks.append(
            build_zone(
                ZONE_TRUSTED_ACCESS,
                trusted_access_ifaces,
                input_policy=FIREWALL_TARGET_ACCEPT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if transit_access_ifaces:
        blocks.append(
            build_zone(
                ZONE_TRANSIT_ACCESS,
                transit_access_ifaces,
                input_policy=FIREWALL_TARGET_REJECT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )
        blocks.append(build_rule_allow_dns_transit_access().strip())

    if router_name in cfg.mesh_hubs_by_name:
        hub = cfg.mesh_hubs_by_name[router_name]

        for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
            link = compute_mesh_link_params(cfg, hub, target_name)
            blocks.append(
                build_rule_allow_port_wan(
                    mesh_firewall_rule_name(hub.name, target_name),
                    link.port,
                    TRANSPORT_UDP,
                ).strip()
            )

        for exit_hub in cfg.exit_hubs:
            blocks.append(
                build_rule_allow_port_wan(
                    exit_reverse_firewall_rule_name(exit_hub.name),
                    router_exit_listen_port(cfg, exit_hub, router_name),
                    TRANSPORT_UDP,
                ).strip()
            )

    for group in access_groups_for_router:
        blocks.append(
            build_rule_allow_port_wan(
                f"Allow-{group.name}",
                group.port,
                (
                    TRANSPORT_TCP
                    if group.protocol == PROTOCOL_OPENVPN
                    else TRANSPORT_UDP
                ),
            ).strip()
        )

    for allow in cfg.firewall_allows:
        targets = expand_firewall_targets(cfg, allow)
        if router_name not in targets:
            continue

        blocks.append(
            build_rule_allow_mesh_src_ip(
                firewall_allow_rule_name(allow.source_name, router_name, allow.kind),
                allow.source_subnet,
                FIREWALL_ZONE_LAN if allow.kind == FIREWALL_ALLOW_KIND_LAN else None,
            ).strip()
        )

    rendered = "\n\n".join(blocks).strip()
    preserved_rendered = preserved_before.strip("\n")
    marker_tail = marker_and_tail.strip("\n")

    parts: list[str] = []
    if rendered:
        parts.append(rendered)
    if preserved_rendered:
        parts.append(preserved_rendered)
    if marker_tail:
        parts.append(marker_tail)

    # Keep the shared section after FIREWALL_MARKER byte-stable with
    # routers/example.  sync_rules.py owns that tail; normalizing the whole
    # file here makes sync_rules.py and generate.py rewrite firewall_part on
    # every run.  Keep the historical leading blank line too: existing
    # firewall_part files intentionally start with an empty first line, and
    # sync_rules.py preserves the generated part byte-for-byte.
    updated = "\n\n".join(parts).rstrip()
    write(path, f"\n{updated}\n" if updated else "")


def list_access_interfaces(cfg: ConfigData, router_name: str) -> list[str]:
    return sorted(group.name for group in cfg.access.get(router_name, []))


def build_babeld_text(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
) -> str:
    lines = [
        "config general",
        f"    option log_file '{BABELD_LOG_FILE}'",
        f"    option ubus_bindings '{BABELD_UBUS_BINDINGS}'",
        "",
    ]

    for iface in mesh_ifaces + exit_ifaces:
        lines += [
            "config interface",
            f"    option ifname '{iface}'",
            f"    option type '{BABELD_TUNNEL_TYPE}'",
            f"    option split_horizon '{BABELD_SPLIT_HORIZON}'",
            f"    option hello_interval '{BABELD_HELLO_INTERVAL}'",
            f"    option update_interval '{BABELD_UPDATE_INTERVAL}'",
            "",
        ]

    lines += [
        "config filter",
        "    option type 'redistribute'",
        f"    option if '{BABELD_LAN_IFACE}'",
        "    option action 'allow'",
        "",
    ]

    for iface in list_access_interfaces(cfg, router_name):
        lines += [
            "config filter",
            "    option type 'redistribute'",
            f"    option if '{iface}'",
            "    option action 'allow'",
            "",
        ]

    lines += [
        "config filter",
        "    option type 'redistribute'",
        "    option local 'true'",
        "    option action 'deny'",
        "",
        "config filter",
        "    option type 'redistribute'",
        "    option action 'deny'",
        "",
    ]

    return "\n" + "\n".join(lines).rstrip() + "\n"


def update_babeld(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
) -> None:
    path = router_path(cfg, router_name, "babeld")
    write(path, build_babeld_text(cfg, router_name, mesh_ifaces, exit_ifaces))


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Generator: mesh/exit AmneziaWG + access WireGuard/AmneziaWG/OpenVPN + "
            "babeld + firewall + bootstrap updates"
        )
    )
    ap.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="path to JSON config file (default: config.json)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="regenerate mesh/exit keys; access secrets are preserved",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="print detailed generation information",
    )
    args = ap.parse_args()

    raw_cfg = load_json_config(Path(args.config))
    cfg = build_config_data(raw_cfg)

    need("openssl")
    existing = load_existing_network_cfgs(cfg)

    secrets_force = args.force
    access_force = False

    access_blocks, access_states, access_names = build_access_state(
        cfg=cfg,
        existing_all=existing,
        access_groups=cfg.access,
        force=access_force,
        verbose=args.verbose,
    )

    generate_openvpn_access(cfg=cfg, force=access_force, verbose=args.verbose)
    generate_openvpn_client_files(cfg=cfg, force=access_force, verbose=args.verbose)
    generate_wireguard_client_files(
        cfg=cfg,
        states_by_router=access_states,
        verbose=args.verbose,
    )

    keep_exit_hubs = {h.name for h in cfg.exit_hubs}
    reconcile_server_dirs(keep_exit_hubs)
    mesh_blocks, mesh_ifaces, _mesh_states = build_mesh_state(
        cfg=cfg,
        existing_all=existing,
        force=secrets_force,
        verbose=args.verbose,
    )

    router_exit_blocks: dict[str, dict[str, str]] = {r: {} for r in cfg.router_names}
    router_exit_ipip_blocks: dict[str, dict[str, str]] = {
        r: {} for r in cfg.router_names
    }
    router_exit_ifaces: dict[str, list[str]] = {r: [] for r in cfg.router_names}
    router_exit_ipip_ifaces: dict[str, list[str]] = {r: [] for r in cfg.router_names}
    hub_states: dict[str, list[RouterExitState]] = {h.name: [] for h in cfg.exit_hubs}
    exit_exit_aliases_by_hub: dict[str, list[str]] = {h.name: [] for h in cfg.exit_hubs}

    for hub in cfg.exit_hubs:
        ensure_server_layout(hub.name)

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        left_alias = build_exit_exit_alias(cfg, left_hub.name, right_hub.name)
        right_alias = build_exit_exit_alias(cfg, right_hub.name, left_hub.name)
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        key = exit_exit_link_key(left_hub.name, right_hub.name)
        awg = awg_for_infra_link(key)
        keys = build_material_for_exit_exit(
            cfg=cfg,
            left_hub=left_hub,
            right_hub=right_hub,
            force=secrets_force,
        )

        write(
            server_client_conf_path(left_hub.name, left_alias),
            build_exit_exit_server_conf(left_hub, right_hub, link, keys, awg),
        )
        write(
            server_client_conf_path(right_hub.name, right_alias),
            build_exit_exit_server_conf(right_hub, left_hub, link, keys, awg),
        )
        exit_exit_aliases_by_hub[left_hub.name].append(left_alias)
        exit_exit_aliases_by_hub[right_hub.name].append(right_alias)

        if args.verbose:
            print(
                f"EXIT-EXIT {left_hub.name:<8} Out -> {right_hub.name:<8} In "
                f"aliases={left_alias}/{right_alias} "
                f"ports={link.left_port}/{link.right_port}"
            )

    for hub in cfg.exit_hubs:
        for router_name in cfg.router_names:
            router_cfg = existing[router_name]
            blocks: list[str] = []

            if exit_hub_is_public(hub):
                client_alias = build_exit_client_alias(cfg, hub.name, router_name)
                link = compute_exit_link_params(cfg, hub, router_name)
                awg = awg_for_infra_link(exit_link_key(hub.name, router_name))
                iface_name = exit_out_iface_name(hub.name)

                keys = build_material_for_exit(
                    router_name=router_name,
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=secrets_force,
                )

                write(
                    server_client_conf_path(hub.name, client_alias),
                    build_server_direct_conf(client_alias, hub, link, keys, awg),
                )
                blocks.append(
                    build_exit_out_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

                hub_states[hub.name].append(
                    RouterExitState(
                        router_name=router_name,
                        client_alias=client_alias,
                        hub=hub,
                        link=link,
                        keys=keys,
                        awg=awg,
                    )
                )

                if args.verbose:
                    print(
                        f"EXIT-OUT {router_name:<10} -> {hub.name:<8} "
                        f"alias={client_alias:<16} port={link.port:<5}"
                    )

            if router_is_public_mesh_hub(cfg, router_name):
                client_alias = build_exit_reverse_client_alias(
                    cfg, hub.name, router_name
                )
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                key = exit_reverse_link_key(hub.name, router_name)
                awg = awg_for_infra_link(key)
                iface_name = exit_in_iface_name(hub.name)

                keys = build_material_for_exit_reverse(
                    hub=hub,
                    client_alias=client_alias,
                    router_iface_name=iface_name,
                    router_cfg=router_cfg,
                    force=secrets_force,
                )

                write(
                    server_client_conf_path(hub.name, client_alias),
                    build_server_reverse_conf(
                        cfg, router_name, client_alias, hub, link, keys, awg
                    ),
                )
                blocks.append(
                    build_exit_in_network_interface_block(hub, link, keys, awg)
                )
                router_exit_ifaces[router_name].append(iface_name)

                hub_states[hub.name].append(
                    RouterExitState(
                        router_name=router_name,
                        client_alias=client_alias,
                        hub=hub,
                        link=link,
                        keys=keys,
                        awg=awg,
                    )
                )

                if args.verbose:
                    print(
                        f"EXIT-IN  {hub.name:<8} -> {router_name:<10} "
                        f"alias={client_alias:<16} port={link.port:<5}"
                    )

            if blocks:
                router_exit_blocks[router_name][hub.name] = "\n".join(
                    block.strip() for block in blocks
                )

            router_exit_ipip_blocks[router_name][hub.name] = (
                build_exit_ipip_interface_block(
                    cfg,
                    router_name,
                    hub,
                )
            )
            router_exit_ipip_ifaces[router_name].append(
                router_exit_ipip_iface_name(hub.name)
            )

        keep_server_aliases: set[str] = set(exit_exit_aliases_by_hub[hub.name])
        if exit_hub_is_public(hub):
            keep_server_aliases |= {
                build_exit_client_alias(cfg, hub.name, router_name)
                for router_name in cfg.router_names
            }
        keep_server_aliases |= {
            build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
            for mesh_hub in cfg.mesh_hubs
        }
        remove_stale_server_amneziawg_confs(hub.name, keep_server_aliases)

        write(
            server_babeld_conf_path(hub.name),
            build_server_babeld_conf(
                hub, hub_states[hub.name], exit_exit_aliases_by_hub[hub.name]
            ),
        )
        write(
            server_path(hub.name, "etc", "awg-server.env"),
            build_server_env(
                cfg, hub, hub_states[hub.name], exit_exit_aliases_by_hub[hub.name]
            ),
        )
        write_server_ipsets(cfg, hub.name)

    for router_name in cfg.router_names:
        mesh_text = mesh_blocks[router_name].strip()
        exit_text = "\n".join(
            router_exit_blocks[router_name][hub.name].strip()
            for hub in cfg.exit_hubs
            if hub.name in router_exit_blocks[router_name]
        ).strip()
        ipip_text = "\n".join(
            router_exit_ipip_blocks[router_name][hub.name].strip()
            for hub in router_exit_order_hubs(cfg, router_name)
            if hub.name in router_exit_ipip_blocks[router_name]
        ).strip()
        access_text = access_blocks.get(router_name, "").strip()

        update_network_part(
            cfg=cfg,
            router_name=router_name,
            mesh_text=mesh_text,
            exit_text=exit_text,
            ipip_text=ipip_text,
            access_text=access_text,
            access_names=access_names,
        )
        update_babeld(
            cfg=cfg,
            router_name=router_name,
            mesh_ifaces=mesh_ifaces[router_name],
            exit_ifaces=sorted(set(router_exit_ifaces[router_name])),
        )
        active_exit_ipip_ifaces = [
            router_exit_ipip_iface_name(hub.name)
            for hub in router_exit_order_hubs(cfg, router_name)
        ]
        update_firewall_part(
            cfg=cfg,
            router_name=router_name,
            mesh_ifaces=mesh_ifaces[router_name],
            exit_ifaces=sorted(set(router_exit_ifaces[router_name])),
            exit_ipip_ifaces=sorted(set(active_exit_ipip_ifaces)),
            access_groups_for_router=cfg.access.get(router_name, []),
        )
        update_bootstrap(cfg=cfg, router_name=router_name)
        update_openvpn_uci(
            cfg=cfg,
            router_name=router_name,
            groups=cfg.access.get(router_name, []),
        )
        write_router_ipsets(cfg, router_name)


if __name__ == "__main__":
    main()
