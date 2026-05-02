#!/bin/sh

ENV_FILE="${ENV_FILE:-/etc/awg-server.env}"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1091 disable=SC1090
    . "$ENV_FILE"
fi

IP_BIN="${IP_BIN:-/usr/sbin/ip}"
IPTABLES_BIN="${IPTABLES_BIN:-/usr/sbin/iptables}"
IPSET_BIN="${IPSET_BIN:-/usr/sbin/ipset}"
SYSCTL_BIN="${SYSCTL_BIN:-/usr/sbin/sysctl}"
MODPROBE_BIN="${MODPROBE_BIN:-/usr/sbin/modprobe}"
CURL_BIN="${CURL_BIN:-/usr/bin/curl}"
AWK_BIN="${AWK_BIN:-/usr/bin/awk}"
SED_BIN="${SED_BIN:-/usr/bin/sed}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"

SERVER_NAME="${SERVER_NAME:-unknown}"
NODE_ADDR4="${NODE_ADDR4:-}"
NODE_IP="${NODE_ADDR4%%/*}"
NODE_IFACE="${NODE_IFACE:-awg-node}"
LISTEN_IP="${LISTEN_IP:-}"
EXIT_IP="${EXIT_IP:-}"
IPIP_IFACE="${IPIP_IFACE:-ipip-exit}"
IPIP_ADDR4="${IPIP_ADDR4:-10.254.0.1/31}"
IPIP_LOCAL="${IPIP_LOCAL:-${IPIP_ADDR4%%/*}}"
IPIP_TTL="${IPIP_TTL:-64}"
IPIP_MTU="${IPIP_MTU:-}"
EXIT_SUBNET="${EXIT_SUBNET:-}"
EXIT_SUBNETS="${EXIT_SUBNETS:-$EXIT_SUBNET}"
IPSET_NAME="${IPSET_NAME:-exit_direct}"
NAT_CHAIN="${NAT_CHAIN:-AWG_SERVER_NAT}"
FORWARD_CHAIN="${FORWARD_CHAIN:-AWG_SERVER_FORWARD}"
ROUTE_PROBE_IP="${ROUTE_PROBE_IP:-1.1.1.1}"
AWG_SERVICES="${AWG_SERVICES:-}"

BABELD_CONF="${BABELD_CONF:-}"
BABELD_CONF_NAME="${BABELD_CONF##*/}"
BABELD_PIDFILE="/run/${BABELD_CONF_NAME%.conf}.pid"
BABELD_START_TIMEOUT="${BABELD_START_TIMEOUT:-10}"
BABELD_STOP_TIMEOUT="${BABELD_STOP_TIMEOUT:-3}"

URL_GH_RAW="${URL_GH_RAW:-https://raw.githubusercontent.com}"
IPSETS_DIR="${IPSETS_DIR:-/etc/ipsets}"
STATIC_DIRECT_NAME="${STATIC_DIRECT_NAME:-direct-static.txt}"
OUT_DIRECT_NAME="${OUT_DIRECT_NAME:-direct.txt}"

STATIC_DIRECT="$IPSETS_DIR/$STATIC_DIRECT_NAME"
OUT_DIRECT="$IPSETS_DIR/$OUT_DIRECT_NAME"
TMP_DIRECT="${OUT_DIRECT}.tmp"
TMP_SORTED="${TMP_DIRECT}.sorted"

URL_IPVERSE_RIR="${URL_IPVERSE_RIR:-$URL_GH_RAW/ipverse/country-ip-blocks/master}"
URL_IPVERSE_ASN="${URL_IPVERSE_ASN:-$URL_GH_RAW/ipverse/as-ip-blocks/master}"

DIRECT_COUNTRIES="${DIRECT_COUNTRIES:-}"
DIRECT_ASNS="${DIRECT_ASNS:-}"
UPDATE_IPSETS_CURL_CONNECT_TIMEOUT="${UPDATE_IPSETS_CURL_CONNECT_TIMEOUT:-10}"
UPDATE_IPSETS_CURL_MAX_TIME="${UPDATE_IPSETS_CURL_MAX_TIME:-60}"
UPDATE_IPSETS_CURL_RETRY="${UPDATE_IPSETS_CURL_RETRY:-3}"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

usage() {
    cat >&2 <<EOF_USAGE
Usage: $0 <mode>

Modes:
  network-up      enable forwarding, IPIP receiver, existing guard, AWG services and NAT/SNAT
  network-down    remove guard, NAT chain, AWG services and IPIP receiver
  guard           refresh direct ipset and install/update FORWARD guard chain
EOF_USAGE
    exit 2
}

need_exit_subnets() {
    [ -n "$EXIT_SUBNETS" ] || die "EXIT_SUBNETS is not set in $ENV_FILE"
}

default_iface() {
    # shellcheck disable=SC2016
    "$IP_BIN" -o route get "$ROUTE_PROBE_IP" \
        | "$AWK_BIN" '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}'
}

ensure_node_iface() {
    [ -n "$NODE_IFACE" ] || die "NODE_IFACE is not set"

    if "$IP_BIN" link show "$NODE_IFACE" >/dev/null 2>&1; then
        return 0
    fi

    if [ -x "$MODPROBE_BIN" ]; then
        "$MODPROBE_BIN" dummy >/dev/null 2>&1 || true
    fi

    "$IP_BIN" link add "$NODE_IFACE" type dummy \
        || die "failed to create node interface $NODE_IFACE"
}

ensure_node_ip() {
    [ -n "$NODE_ADDR4" ] || return 0

    ensure_node_iface

    "$IP_BIN" addr replace "$NODE_ADDR4" dev "$NODE_IFACE" \
        || die "failed to set NODE_ADDR4=$NODE_ADDR4 on $NODE_IFACE"

    "$IP_BIN" link set "$NODE_IFACE" up \
        || die "failed to bring $NODE_IFACE up"
}

remove_node_ip() {
    [ -n "$NODE_ADDR4" ] || return 0
    [ -n "$NODE_IFACE" ] || return 0

    "$IP_BIN" addr del "$NODE_ADDR4" dev "$NODE_IFACE" >/dev/null 2>&1 || true
}

ensure_ipip() {
    [ -n "$IPIP_IFACE" ] || die "IPIP_IFACE is not set"
    [ -n "$IPIP_ADDR4" ] || die "IPIP_ADDR4 is not set"
    [ -n "$IPIP_LOCAL" ] || die "IPIP_LOCAL is not set"

    if [ -x "$MODPROBE_BIN" ]; then
        "$MODPROBE_BIN" ipip >/dev/null 2>&1 || true
    fi

    if ! "$IP_BIN" link show "$IPIP_IFACE" >/dev/null 2>&1; then
        "$IP_BIN" tunnel add "$IPIP_IFACE" mode ipip local "$IPIP_LOCAL" ttl "$IPIP_TTL" \
            || die "failed to create IPIP receiver $IPIP_IFACE local=$IPIP_LOCAL"
    fi

    "$IP_BIN" addr replace "$IPIP_ADDR4" dev "$IPIP_IFACE" \
        || die "failed to set $IPIP_ADDR4 on $IPIP_IFACE"

    if [ -n "$IPIP_MTU" ]; then
        "$IP_BIN" link set "$IPIP_IFACE" mtu "$IPIP_MTU" \
            || die "failed to set MTU $IPIP_MTU on $IPIP_IFACE"
    fi

    "$IP_BIN" link set "$IPIP_IFACE" up \
        || die "failed to bring $IPIP_IFACE up"
}

ensure_nat_chain() {
    "$IPTABLES_BIN" -t nat -N "$NAT_CHAIN" 2>/dev/null || true

    "$IPTABLES_BIN" -t nat -F "$NAT_CHAIN" \
        || die "failed to flush NAT chain $NAT_CHAIN"

    if ! "$IPTABLES_BIN" -t nat -C POSTROUTING -j "$NAT_CHAIN" 2>/dev/null; then
        "$IPTABLES_BIN" -t nat -A POSTROUTING -j "$NAT_CHAIN" \
            || die "failed to attach NAT chain $NAT_CHAIN"
    fi
}

remove_nat_chain() {
    while "$IPTABLES_BIN" -t nat -C POSTROUTING -j "$NAT_CHAIN" 2>/dev/null; do
        "$IPTABLES_BIN" -t nat -D POSTROUTING -j "$NAT_CHAIN" || break
    done

    "$IPTABLES_BIN" -t nat -F "$NAT_CHAIN" 2>/dev/null || true
    "$IPTABLES_BIN" -t nat -X "$NAT_CHAIN" 2>/dev/null || true
}

start_awg_services() {
    for service in $AWG_SERVICES; do
        [ -n "$service" ] || continue
        "$SYSTEMCTL_BIN" start "$service" \
            || die "failed to start $service"
    done
}

stop_awg_services() {
    for service in $AWG_SERVICES; do
        [ -n "$service" ] || continue
        "$SYSTEMCTL_BIN" stop "$service" 2>/dev/null || true
    done
}

babeld_pid_alive() {
    _pid="$1"

    case "$_pid" in
        '' | *[!0-9]*) return 1 ;;
        *) ;;
    esac

    kill -0 "$_pid" 2>/dev/null
}

babeld_pid_from_file() {
    [ -n "$BABELD_PIDFILE" ] || return 1
    [ -f "$BABELD_PIDFILE" ] || return 1
    head -n 1 "$BABELD_PIDFILE" 2>/dev/null
}

wait_for_babeld_pid() {
    waited=0

    while [ "$waited" -lt "$BABELD_START_TIMEOUT" ]; do
        pid="$(babeld_pid_from_file || true)"
        if babeld_pid_alive "$pid"; then
            echo "$pid"
            return 0
        fi

        sleep 1
        waited=$((waited + 1))
    done

    return 1
}

start_babeld() {
    [ -n "$BABELD_CONF" ] || die "BABELD_CONF is not set in $ENV_FILE"
    [ -x /usr/sbin/babeld ] || die "babeld binary is not executable: /usr/sbin/babeld"
    [ -f "$BABELD_CONF" ] || die "missing babeld config: $BABELD_CONF"

    pid="$(babeld_pid_from_file || true)"
    if babeld_pid_alive "$pid"; then
        echo "OK: babeld already running, pid=$pid"
        return 0
    fi

    rm -f "$BABELD_PIDFILE"

    /usr/sbin/babeld -D -I "$BABELD_PIDFILE" -c "$BABELD_CONF" \
        || die "failed to start babeld"

    pid="$(wait_for_babeld_pid || true)"
    [ -n "$pid" ] || die "babeld did not create a live pidfile in time: $BABELD_PIDFILE"

    echo "OK: babeld started, pid=$pid, conf=$BABELD_CONF"
}

stop_babeld() {
    [ -n "$BABELD_PIDFILE" ] || return 0

    pid="$(babeld_pid_from_file || true)"
    if ! babeld_pid_alive "$pid"; then
        rm -f "$BABELD_PIDFILE"
        return 0
    fi

    kill "$pid" 2>/dev/null || true

    waited=0
    while babeld_pid_alive "$pid"; do
        [ "$waited" -lt "$BABELD_STOP_TIMEOUT" ] || break
        sleep 1
        waited=$((waited + 1))
    done

    if babeld_pid_alive "$pid"; then
        kill -KILL "$pid" 2>/dev/null || true
    fi

    rm -f "$BABELD_PIDFILE"
    echo "OK: babeld stopped, pid=$pid"
}

install_nat_rules() {
    iface="$(default_iface)"
    [ -n "$iface" ] || die "failed to determine default interface"

    ensure_nat_chain

    for subnet in $EXIT_SUBNETS; do
        [ -n "$subnet" ] || continue

        if [ -n "$EXIT_IP" ]; then
            "$IPTABLES_BIN" -t nat -A "$NAT_CHAIN" \
                -s "$subnet" -o "$iface" -j SNAT --to-source "$EXIT_IP" \
                || die "failed to install SNAT rule for $subnet"
        else
            "$IPTABLES_BIN" -t nat -A "$NAT_CHAIN" \
                -s "$subnet" -o "$iface" -j MASQUERADE \
                || die "failed to install MASQUERADE rule for $subnet"
        fi
    done
}

network_up() {
    need_exit_subnets

    "$SYSCTL_BIN" -w net.ipv4.ip_forward=1 >/dev/null \
        || die "failed to enable IPv4 forwarding"

    ensure_node_ip
    ensure_ipip
    guard_existing
    start_awg_services
    start_babeld
    install_nat_rules

    status="OK: ${SERVER_NAME} network up, node_ip=${NODE_IP:-none}"
    status="${status}, listen_ip=${LISTEN_IP:-none}"
    status="${status}, ipip=${IPIP_IFACE}/${IPIP_ADDR4}"
    if [ -n "$IPIP_MTU" ]; then
        status="${status}, ipip_mtu=${IPIP_MTU}"
    fi
    if [ -n "$EXIT_IP" ]; then
        echo "${status}, exit_ip=${EXIT_IP}"
    else
        echo "${status}, exit_ip=MASQUERADE"
    fi
}

network_down() {
    remove_forward_chain
    stop_babeld
    stop_awg_services
    remove_nat_chain
    "$IP_BIN" link del "$IPIP_IFACE" >/dev/null 2>&1 || true
    remove_node_ip
    echo "OK: ${SERVER_NAME} network down"
}

append_static_direct() {
    if [ ! -s "$STATIC_DIRECT" ]; then
        echo "ERROR: missing or empty static direct list: $STATIC_DIRECT" >&2
        return 1
    fi

    "$SED_BIN" '/^[[:space:]]*#/d; /^[[:space:]]*$/d' \
        "$STATIC_DIRECT" >>"$TMP_DIRECT"
}

append_url_list() {
    url="$1"
    label="$2"

    data="$("$CURL_BIN" -fsSL \
        --connect-timeout "$UPDATE_IPSETS_CURL_CONNECT_TIMEOUT" \
        --max-time "$UPDATE_IPSETS_CURL_MAX_TIME" \
        --retry "$UPDATE_IPSETS_CURL_RETRY" \
        "$url")" || {
        echo "ERROR: failed to fetch $label from $url" >&2
        return 1
    }

    lines="$(
        printf '%s\n' "$data" \
            | "$SED_BIN" '/^[[:space:]]*#/d; /^[[:space:]]*$/d'
    )"

    if [ -z "$lines" ]; then
        echo "ERROR: empty $label list from $url" >&2
        return 1
    fi

    printf '%s\n' "$lines" >>"$TMP_DIRECT"
    echo "OK: fetched $label from $url"
    return 0
}

append_country_lists() {
    for country in $DIRECT_COUNTRIES; do
        case "$country" in
            [a-z][a-z]) ;;
            *)
                echo "ERROR: bad country code: $country" >&2
                return 1
                ;;
        esac

        append_url_list \
            "$URL_IPVERSE_RIR/country/$country/ipv4-aggregated.txt" \
            "country:$country" || return 1
    done
}

append_asn_lists() {
    for asn in $DIRECT_ASNS; do
        case "$asn" in
            '' | *[!0-9]*)
                echo "ERROR: bad ASN: $asn" >&2
                return 1
                ;;
            *) ;;
        esac

        append_url_list \
            "$URL_IPVERSE_ASN/as/$asn/ipv4-aggregated.txt" \
            "as:$asn" || return 1
    done
}

build_direct_list() {
    mkdir -p "$IPSETS_DIR" || die "failed to create $IPSETS_DIR"
    rm -f "$TMP_DIRECT" "$TMP_SORTED"

    if ! append_static_direct; then
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        exit 1
    fi

    if ! append_country_lists; then
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        exit 1
    fi

    if ! append_asn_lists; then
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        exit 1
    fi

    if [ ! -s "$TMP_DIRECT" ]; then
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        die "generated direct list is empty"
    fi

    sort -u "$TMP_DIRECT" >"$TMP_SORTED" || {
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        die "failed to sort $TMP_DIRECT"
    }

    mv -f "$TMP_SORTED" "$TMP_DIRECT" || {
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        die "failed to replace sorted tmp list"
    }

    mv -f "$TMP_DIRECT" "$OUT_DIRECT" \
        || die "failed to update $OUT_DIRECT"
}

restore_ipset() {
    [ -s "$OUT_DIRECT" ] || die "missing or empty direct list: $OUT_DIRECT"

    {
        echo "create $IPSET_NAME hash:net family inet hashsize 16384 maxelem 262144 -exist"
        echo "flush $IPSET_NAME"
        # shellcheck disable=SC2016
        "$AWK_BIN" -v set="$IPSET_NAME" \
            '{ print "add " set " " $0 " -exist" }' \
            "$OUT_DIRECT"
    } | "$IPSET_BIN" restore || die "ipset restore failed"
}

ipset_update() {
    build_direct_list
    restore_ipset

    echo "OK: refreshed $IPSET_NAME ipset from $OUT_DIRECT"
}

ensure_forward_chain() {
    "$IPTABLES_BIN" -N "$FORWARD_CHAIN" 2>/dev/null || true

    "$IPTABLES_BIN" -F "$FORWARD_CHAIN" \
        || die "failed to flush FORWARD chain $FORWARD_CHAIN"

    if ! "$IPTABLES_BIN" -C FORWARD -j "$FORWARD_CHAIN" 2>/dev/null; then
        "$IPTABLES_BIN" -I FORWARD 1 -j "$FORWARD_CHAIN" \
            || die "failed to attach FORWARD chain $FORWARD_CHAIN"
    fi
}

remove_forward_chain() {
    while "$IPTABLES_BIN" -C FORWARD -j "$FORWARD_CHAIN" 2>/dev/null; do
        "$IPTABLES_BIN" -D FORWARD -j "$FORWARD_CHAIN" || break
    done

    "$IPTABLES_BIN" -F "$FORWARD_CHAIN" 2>/dev/null || true
    "$IPTABLES_BIN" -X "$FORWARD_CHAIN" 2>/dev/null || true
}

guard_rules() {
    need_exit_subnets
    ensure_forward_chain

    iface="$(default_iface)"
    [ -n "$iface" ] || die "failed to determine default interface"

    "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
        -m conntrack --ctstate ESTABLISHED,RELATED \
        -j ACCEPT \
        || die "failed to install established/related guard rule"

    for subnet in $EXIT_SUBNETS; do
        [ -n "$subnet" ] || continue

        "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
            -s "$subnet" -o "$iface" \
            -m set --match-set "$IPSET_NAME" dst \
            -j DROP \
            || die "failed to install $IPSET_NAME WAN guard rule for $subnet"
    done

    echo "OK: installed $FORWARD_CHAIN rules for $IPSET_NAME on wan=$iface"
}

guard_existing() {
    restore_ipset
    guard_rules
    echo "OK: installed $IPSET_NAME guard from existing $OUT_DIRECT"
}

guard_refresh() {
    ipset_update
    guard_rules
}

mode="${1:-}"
case "$mode" in
    network-up) network_up ;;
    network-down) network_down ;;
    guard) guard_refresh ;;
    *) usage ;;
esac
