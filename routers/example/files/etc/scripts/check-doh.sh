#!/bin/sh

if [ -r /etc/router-autoinstall.env ]; then
    # Generated file, loaded once at startup. Restart to apply changes.
    # shellcheck disable=SC1091
    . /etc/router-autoinstall.env
fi

DOMAIN="${CHECK_DOH_DOMAIN:-google.com}"
INTERVAL="${CHECK_DOH_INTERVAL:-5}"

RESOLV="${CHECK_DOH_RESOLV:-/tmp/resolv.conf.d/resolv.conf.auto}"
RESOLV_WAIT_MAX="${CHECK_DOH_RESOLV_WAIT_MAX:-300}"
PROVIDER_DOMAINS="${CHECK_DOH_PROVIDER_DOMAINS:-ru xn--p1ai}"

get_doh_endpoints_from_uci() {
    i=0
    eps_doh=""

    while uci -q get "https-dns-proxy.@https-dns-proxy[$i]" >/dev/null 2>&1; do
        p="$(uci -q get "https-dns-proxy.@https-dns-proxy[$i].listen_port" 2>/dev/null)"
        if [ -n "$p" ]; then
            if [ -z "$eps_doh" ]; then
                eps_doh="127.0.0.1:${p}"
            else
                eps_doh="$eps_doh 127.0.0.1:${p}"
            fi
        fi
        i=$((i + 1))
    done

    echo "$eps_doh"
}

resolv_has_nameservers() {
    [ -f "$RESOLV" ] || return 1
    grep -qE '^[[:space:]]*nameserver[[:space:]]+' "$RESOLV" 2>/dev/null
}

wait_for_resolv_nameservers() {
    waited=0

    while [ "$waited" -lt "$RESOLV_WAIT_MAX" ]; do
        if resolv_has_nameservers; then
            return 0
        fi

        sleep 1
        waited=$((waited + 1))
    done

    return 1
}

get_nameservers_from_resolv() {
    eps_resolv=""
    resolv_dns="$(
        sed -n \
            's/^[[:space:]]*nameserver[[:space:]]\{1,\}\([^[:space:]#][^[:space:]#]*\).*$/\1/p' \
            "$RESOLV" 2>/dev/null | xargs echo
    )"

    for dns in $resolv_dns; do
        if [ -n "$dns" ]; then
            if [ -z "$eps_resolv" ]; then
                eps_resolv="${dns}:53"
            else
                eps_resolv="$eps_resolv ${dns}:53"
            fi
        fi
    done

    echo "$eps_resolv"
}

build_endpoints() {
    eps_doh="$(get_doh_endpoints_from_uci)"
    eps_resolv="$(get_nameservers_from_resolv)"

    if [ -n "$eps_doh" ] && [ -n "$eps_resolv" ]; then
        echo "$eps_doh $eps_resolv"
    elif [ -n "$eps_doh" ]; then
        echo "$eps_doh"
    else
        echo "$eps_resolv"
    fi
}

nslookup_ok() {
    _ep="$1"
    nslookup "$DOMAIN" "$_ep" >/dev/null 2>&1
}

first_working_endpoint() {
    for _ep in "$@"; do
        if nslookup_ok "$_ep"; then
            echo "$_ep"
            return 0
        fi
    done

    return 1
}

last_endpoint() {
    _last=""

    for _ep in "$@"; do
        _last="$_ep"
    done

    [ -n "$_last" ] || return 1
    echo "$_last"
}

dnsmasq_server_value() {
    _ep="$1"
    _ip="${_ep%:*}"
    _port="${_ep##*:}"
    echo "${_ip}#${_port}"
}

endpoint_from_dnsmasq_server_value() {
    _value="$1"

    case "$_value" in
        /*)
            return 1
            ;;
        *'#'*)
            _ip="${_value%#*}"
            _port="${_value##*#}"
            echo "${_ip}:${_port}"
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

current_endpoint() {
    for _server in $(uci -q get dhcp.@dnsmasq[0].server 2>/dev/null); do
        _ep="$(endpoint_from_dnsmasq_server_value "$_server" || true)"
        if [ -n "$_ep" ]; then
            echo "$_ep"
            return 0
        fi
    done

    return 1
}

dnsmasq_domain_server_value() {
    _domain_server_domain="$1"
    _domain_server_ep="$2"
    _domain_server_upstream="$(dnsmasq_server_value "$_domain_server_ep")"
    echo "/${_domain_server_domain}/${_domain_server_upstream}"
}

add_dnsmasq_provider_domain_servers() {
    _provider_eps_resolv="$(get_nameservers_from_resolv)"

    for _provider_domain in $PROVIDER_DOMAINS; do
        for _provider_ep_resolv in $_provider_eps_resolv; do
            _provider_val="$(
                dnsmasq_domain_server_value "$_provider_domain" "$_provider_ep_resolv"
            )"
            uci -q add_list "dhcp.@dnsmasq[0].server=${_provider_val}" || return 1
        done
    done

    return 0
}

set_dnsmasq_server_endpoint() {
    _set_ep="$1"
    _set_val="$(dnsmasq_server_value "$_set_ep")"

    uci -q del dhcp.@dnsmasq[0].server >/dev/null 2>&1
    add_dnsmasq_provider_domain_servers || return 1
    uci -q add_list "dhcp.@dnsmasq[0].server=${_set_val}" || return 1
    uci -q commit dhcp || return 1
    /etc/init.d/dnsmasq restart >/dev/null 2>&1

    return 0
}

apply_once() {
    endpoints="$(build_endpoints)"
    cur=""
    target=""

    if [ -z "$endpoints" ]; then
        echo "no DNS endpoints found: no https-dns-proxy listen_port and no nameserver in $RESOLV"
        return 0
    fi

    cur="$(current_endpoint || true)"

    # shellcheck disable=SC2086
    target="$(first_working_endpoint $endpoints || true)"

    if [ -z "$target" ]; then
        # shellcheck disable=SC2086
        target="$(last_endpoint $endpoints || true)"
        echo "no working DNS endpoint; use fallback=${target:-none} endpoints=[$endpoints]"
    fi

    [ -n "$target" ] || return 0
    [ "$cur" = "$target" ] && return 0

    echo "switch DNS endpoint: current=${cur:-none} target=$target"
    set_dnsmasq_server_endpoint "$target"
}

case "${1:-run}" in
    once)
        apply_once
        ;;

    run)
        if ! wait_for_resolv_nameservers; then
            echo "ERROR: no nameserver entries appeared in $RESOLV within ${RESOLV_WAIT_MAX}s"
            exit 1
        fi

        echo "started: domain=$DOMAIN interval=${INTERVAL}s"
        echo "provider_domains=[$PROVIDER_DOMAINS] resolv=$RESOLV"

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
