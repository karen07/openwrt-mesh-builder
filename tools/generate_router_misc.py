#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re

try:
    from .common import *
    from .default import OWMB_ENC_SECRET_MARKER, OWMB_PLAIN_SECRET_MARKER
except ImportError:
    from common import *  # type: ignore
    from default import OWMB_ENC_SECRET_MARKER, OWMB_PLAIN_SECRET_MARKER  # type: ignore

SECRET_MARKER_RE = re.compile(
    rf"^({re.escape(OWMB_ENC_SECRET_MARKER)}|"
    rf"{re.escape(OWMB_PLAIN_SECRET_MARKER)})\s*\{{\s*(.*?)\s*\}}$",
    re.S,
)

WIFI_MANAGED_COMMENT_RE = re.compile(r"^\s*#\s*Set\s+Wi-Fi(?:\s+radio[01])?\s*$")

WIFI_MANAGED_UCI_RE = re.compile(
    r"^\s*uci\s+(?:-q\s+)?(?:set|delete|add_list)\s+"
    r"wireless\.(?:radio[01]|default_radio[01])(?:\.|\b)"
)

DANGLING_SECRET_CLOSE_RE = re.compile(r"^\s*\}'\s*$")


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


def wrap_secret_marker_for_shell(value: str, width: int = SHELL_SECRET_WRAP_COL) -> str:
    # config.json is the source of truth for Wi-Fi ssid/key values.  Preserve
    # the exact OWMB marker kind and base64/plain payload from config.json; only
    # normalize whitespace inside the marker and wrap long payloads so the shell
    # bootstrap remains readable.
    m = SECRET_MARKER_RE.fullmatch(value)
    if not m:
        return value

    marker = m.group(1)
    payload = re.sub(r"\s+", "", m.group(2))
    lines = [payload[i : i + width] for i in range(0, len(payload), width)]
    return f"{marker}\n{{\n" + "\n".join(lines) + "\n}"


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
