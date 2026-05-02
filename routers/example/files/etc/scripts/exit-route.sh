#!/bin/sh

if [ ! -r /etc/router-autoinstall.env ]; then
    echo "runtime env not readable: /etc/router-autoinstall.env"
    exit 1
fi

# Generated file, loaded once at startup. Restart to apply changes.
# shellcheck disable=SC1091
. /etc/router-autoinstall.env

TABLE="${EXIT_ROUTE_TABLE:-200}"
INTERVAL="${EXIT_ROUTE_INTERVAL:-5}"
ROUTE_SECTION="exit${TABLE}"

if [ -z "$EXIT_ROUTE_TARGETS" ]; then
    echo "EXIT_ROUTE_TARGETS is empty in /etc/router-autoinstall.env"
    exit 1
fi

valid_target_name() {
    case "$1" in
        "" | *[!A-Za-z0-9_]*) return 1 ;;
        *) return 0 ;;
    esac
}

target_iface() {
    name="$1"

    valid_target_name "$name" || return 1
    printf 'ip%s\n' "$name"
}

target_prefix() {
    name="$1"

    valid_target_name "$name" || return 1
    eval "printf '%s\n' \"\${EXIT_ROUTE_${name}_PREFIX}\""
}

has_babel_target() {
    name="$1"
    prefix=""

    prefix="$(target_prefix "$name")"
    [ -n "$prefix" ] || return 1

    ip -4 route show "$prefix" proto babel 2>/dev/null | grep -q .
}

target_is_configured() {
    name="$1"
    iface=""
    prefix=""

    iface="$(target_iface "$name")"
    prefix="$(target_prefix "$name")"

    [ -n "$iface" ] && [ -n "$prefix" ]
}

is_target_usable() {
    name="$1"

    target_is_configured "$name" || return 1
    has_babel_target "$name"
}

best_available_target() {
    name=""

    for name in $EXIT_ROUTE_TARGETS; do
        if is_target_usable "$name"; then
            echo "$name"
            return 0
        fi
    done

    return 1
}

current_target() {
    route_iface=""
    name=""
    iface=""

    [ "$(uci -q get "network.$ROUTE_SECTION")" = "route" ] || {
        echo "ABSENT"
        return 0
    }

    [ "$(uci -q get "network.$ROUTE_SECTION.disabled")" = "1" ] && {
        echo "DISABLED"
        return 0
    }

    [ "$(uci -q get "network.$ROUTE_SECTION.table")" = "$TABLE" ] || {
        echo "OTHER"
        return 0
    }

    case "$(uci -q get "network.$ROUTE_SECTION.target")" in
        "0.0.0.0/0" | "default") ;;
        *)
            echo "OTHER"
            return 0
            ;;
    esac

    route_iface="$(uci -q get "network.$ROUTE_SECTION.interface")"

    for name in $EXIT_ROUTE_TARGETS; do
        iface="$(target_iface "$name")"
        if [ -n "$iface" ] && [ "$route_iface" = "$iface" ]; then
            echo "$name"
            return 0
        fi
    done

    echo "OTHER"
}

network_reload() {
    /etc/init.d/network reload
}

install_exit_target() {
    name="$1"
    iface=""
    prefix=""

    iface="$(target_iface "$name")"
    prefix="$(target_prefix "$name")"

    if [ -z "$iface" ] || [ -z "$prefix" ]; then
        echo "bad target config: $name"
        return 1
    fi

    uci -q set "network.$ROUTE_SECTION=route"
    uci -q set "network.$ROUTE_SECTION.table=$TABLE"
    uci -q set "network.$ROUTE_SECTION.target=0.0.0.0/0"
    uci -q set "network.$ROUTE_SECTION.interface=$iface"

    uci -q delete "network.$ROUTE_SECTION.gateway"
    uci -q delete "network.$ROUTE_SECTION.device"
    uci -q delete "network.$ROUTE_SECTION.type"
    uci -q delete "network.$ROUTE_SECTION.disabled"

    uci commit network
    network_reload

    echo "selected exit $name: prefix=$prefix iface=$iface table=$TABLE"
}

disable_exit_route() {
    uci -q set "network.$ROUTE_SECTION=route"
    uci -q set "network.$ROUTE_SECTION.table=$TABLE"
    uci -q set "network.$ROUTE_SECTION.target=0.0.0.0/0"
    uci -q set "network.$ROUTE_SECTION.disabled=1"

    uci -q delete "network.$ROUTE_SECTION.gateway"
    uci -q delete "network.$ROUTE_SECTION.device"
    uci -q delete "network.$ROUTE_SECTION.type"

    uci commit network
    network_reload

    echo "no reachable exit: disabled table $TABLE default route"
}

apply_once() {
    target=""
    cur=""

    target="$(best_available_target || true)"
    cur="$(current_target)"

    if [ -n "$target" ]; then
        [ "$cur" = "$target" ] && return 0
        install_exit_target "$target"
        return 0
    fi

    [ "$cur" = "DISABLED" ] && return 0
    disable_exit_route
}

case "${1:-run}" in
    once)
        apply_once
        ;;

    run)
        echo "started: table=$TABLE"
        echo "route_section=network.$ROUTE_SECTION interval=${INTERVAL}s"
        echo "no-exit behavior: disable table $TABLE default route"

        while true; do
            apply_once
            sleep "$INTERVAL"
        done
        ;;

    *)
        echo "Usage: $0 [run|once]" >&2
        exit 2
        ;;
esac
