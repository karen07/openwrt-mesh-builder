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
AWK_BIN="${AWK_BIN:-/usr/bin/awk}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"

SERVER_NAME="${SERVER_NAME-}"
NODE_ADDR4="${NODE_ADDR4:-}"
NODE_IP="${NODE_ADDR4%%/*}"
NODE_IFACE="${NODE_IFACE-}"
LISTEN_IP="${LISTEN_IP:-}"
EXIT_IP="${EXIT_IP:-}"
IPIP_IFACE="${IPIP_IFACE-}"
IPIP_ADDR4="${IPIP_ADDR4-}"
IPIP_LOCAL="${IPIP_LOCAL:-${IPIP_ADDR4%%/*}}"
IPIP_TTL="${IPIP_TTL:-64}"
IPIP_MTU="${IPIP_MTU:-}"
EXIT_SUBNET="${EXIT_SUBNET:-}"
EXIT_SUBNETS="${EXIT_SUBNETS:-$EXIT_SUBNET}"
IPSET_NAME="${IPSET_NAME-}"
NAT_CHAIN="${NAT_CHAIN:-AWG_SERVER_NAT}"
FORWARD_CHAIN="${FORWARD_CHAIN:-AWG_SERVER_FORWARD}"
ROUTE_PROBE_IP="${ROUTE_PROBE_IP-}"
AWG_SERVICES="${AWG_SERVICES:-}"

BABELD_CONF="${BABELD_CONF:-}"
BABELD_CONF_NAME="${BABELD_CONF##*/}"
BABELD_PIDFILE="/run/${BABELD_CONF_NAME%.conf}.pid"
BABELD_START_TIMEOUT="${BABELD_START_TIMEOUT:-10}"
BABELD_STOP_TIMEOUT="${BABELD_STOP_TIMEOUT:-3}"

# Direct list location is owned by the shared ipsets configuration.
DIRECT_ENV_FILE="${DIRECT_ENV_FILE:-/etc/update-ipsets.env}"
[ -r "$DIRECT_ENV_FILE" ] || {
    echo "Missing $DIRECT_ENV_FILE" >&2
    exit 1
}
# shellcheck disable=SC1090
. "$DIRECT_ENV_FILE"
IPSETS_DIR="${DIR:-/etc/ipsets}"
OUT_DIRECT="$IPSETS_DIR/${OUT_NAME:-direct.txt}"
OUT_MAIN="$IPSETS_DIR/${STATIC_NAME:-main.txt}"
MAIN_IPSET_NAME="${IPSET_NAME}_main"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

validate_runtime_config() {
    [ -n "$SERVER_NAME" ] || die "SERVER_NAME is not set in $ENV_FILE"
    [ -n "$NODE_IFACE" ] || die "NODE_IFACE is not set in $ENV_FILE"
    [ -n "$IPIP_IFACE" ] || die "IPIP_IFACE is not set in $ENV_FILE"
    [ -n "$IPIP_ADDR4" ] || die "IPIP_ADDR4 is not set in $ENV_FILE"
    [ -n "$IPSET_NAME" ] || die "IPSET_NAME is not set in $ENV_FILE"
    [ -n "$ROUTE_PROBE_IP" ] || die "ROUTE_PROBE_IP is not set in $ENV_FILE"
}

usage() {
    cat >&2 <<EOF_USAGE
Usage: $0 <mode>

Modes:
  network-up      enable forwarding, IPIP receiver, existing guard, AWG services and NAT/SNAT
  network-down    remove guard, NAT chain, AWG services and IPIP receiver
  guard           refresh ipsets; restore FORWARD guard if missing
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
    guard_apply startup
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
    # Keep the guard attached until the receiver and mesh transport are down.
    stop_babeld
    stop_awg_services
    "$IP_BIN" link del "$IPIP_IFACE" >/dev/null 2>&1 || true
    remove_nat_chain
    remove_forward_chain
    remove_node_ip
    echo "OK: ${SERVER_NAME} network down"
}

# Fill temporary sets first and swap only after the complete list is loaded.
# The live sets are never flushed while iptables refers to them.
restore_ipset() {
    [ -s "$OUT_MAIN" ] || die "missing or empty main list: $OUT_MAIN"
    [ -s "$OUT_DIRECT" ] || die "missing or empty direct list: $OUT_DIRECT"

    for spec in "$MAIN_IPSET_NAME:$OUT_MAIN" "$IPSET_NAME:$OUT_DIRECT"; do
        set_name="${spec%%:*}"
        file="${spec#*:}"
        staged="${set_name}_next"
        [ "${#staged}" -le 31 ] || die "ipset name is too long: $staged"

        {
            echo "create $staged hash:net family inet hashsize 16384 maxelem 262144 -exist"
            echo "flush $staged"
            # shellcheck disable=SC2016
            "$AWK_BIN" -v set="$staged" \
                'NF && $1 !~ /^#/ { print "add " set " " $1 " -exist" }' \
                "$file"
        } | "$IPSET_BIN" restore || die "failed to load staged ipset $staged"

        "$IPSET_BIN" create "$set_name" hash:net family inet \
            hashsize 16384 maxelem 262144 -exist \
            || die "failed to create active ipset $set_name"
        "$IPSET_BIN" swap "$staged" "$set_name" \
            || die "failed to swap ipset $set_name"
        "$IPSET_BIN" destroy "$staged" \
            || die "failed to remove old staged ipset $staged"
    done
}

# The chain is installed at network-up and kept while lists are refreshed.
prepare_forward_chain() {
    "$IPTABLES_BIN" -N "$FORWARD_CHAIN" 2>/dev/null || true
    "$IPTABLES_BIN" -F "$FORWARD_CHAIN" \
        || die "failed to flush guard chain $FORWARD_CHAIN"
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
    prepare_forward_chain

    iface="$(default_iface)"
    [ -n "$iface" ] || die "failed to determine default interface"

    for subnet in $EXIT_SUBNETS; do
        [ -n "$subnet" ] || continue

        # Final guard: no router can export either main or direct via EXIT.
        for set_name in "$MAIN_IPSET_NAME" "$IPSET_NAME"; do
            "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
                -s "$subnet" -o "$iface" \
                -m set --match-set "$set_name" dst -j DROP \
                || die "failed to install exit guard for $set_name: $subnet"
        done

        # Skip DPI for ordinary web traffic. TCP ports 80 and 443 bypass
        # nDPI; UDP bypasses only 443 so UDP/80 remains available for P2P
        # detection. nDPI keeps protocol state in conntrack.
        "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
            -s "$subnet" -o "$iface" -p tcp \
            -m multiport ! --dports 80,443 \
            -m ndpi --proto bittorrent \
            -j DROP \
            || die "failed to install TCP nDPI BitTorrent guard rule for $subnet"

        "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
            -s "$subnet" -o "$iface" -p udp ! --dport 443 \
            -m ndpi --proto bittorrent \
            -j DROP \
            || die "failed to install UDP nDPI BitTorrent guard rule for $subnet"

        # Feed replies into the same nDPI conntrack state before the
        # ESTABLISHED fast-path, using the same web-port bypass policy.
        "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
            -d "$subnet" -i "$iface" -p tcp \
            -m multiport ! --sports 80,443 \
            -m ndpi --all \
            || die "failed to install TCP nDPI reply inspection rule for $subnet"

        "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
            -d "$subnet" -i "$iface" -p udp ! --sport 443 \
            -m ndpi --all \
            || die "failed to install UDP nDPI reply inspection rule for $subnet"
    done

    "$IPTABLES_BIN" -A "$FORWARD_CHAIN" \
        -m conntrack --ctstate ESTABLISHED,RELATED \
        -j ACCEPT \
        || die "failed to install established/related guard rule"

    # The main and direct DROP rules above are independent final protection.
    # nDPI BitTorrent filtering remains enforced as a second policy.

    if ! "$IPTABLES_BIN" -C FORWARD -j "$FORWARD_CHAIN" 2>/dev/null; then
        "$IPTABLES_BIN" -I FORWARD 1 -j "$FORWARD_CHAIN" \
            || die "failed to attach forward guard"
    fi

    echo "OK: installed $FORWARD_CHAIN main/direct DROP and nDPI BitTorrent guard \
(TCP 80/443 and UDP 443 bypassed) on wan=$iface"
}

guard_apply() {
    restore_ipset
    if [ "$1" = refresh ] \
        && "$IPTABLES_BIN" -C FORWARD -j "$FORWARD_CHAIN" 2>/dev/null; then
        echo "OK: refreshed main/direct ipsets; FORWARD guard unchanged"
        return 0
    fi

    guard_rules
    echo "OK: installed main/direct guard from $OUT_MAIN and $OUT_DIRECT"
}

mode="${1:-}"
validate_runtime_config
# Prevent guard timer and network-up/down from rebuilding the same chains
# or staging sets concurrently.
exec 9>/run/awg-server.lock || die 'failed to open guard lock'
flock -w 180 9 || die 'AWG guard lock timeout'
case "$mode" in
    network-up) network_up ;;
    network-down) network_down ;;
    guard) guard_apply refresh ;;
    *) usage ;;
esac
