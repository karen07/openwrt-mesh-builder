#!/bin/sh

# OpenWrt routers use UCI; Linux servers use their own generated ENV file.
# The generator passes ENV_FILE=/dev/null and explicit staging values.
if [ "${ENV_FILE+x}" != x ] && [ ! -r /etc/config/update_ipsets ] \
    && [ -r /etc/update-ipsets.env ]; then
    ENV_FILE=/etc/update-ipsets.env
fi
if [ "${ENV_FILE+x}" = x ]; then
    [ -r "$ENV_FILE" ] || {
        echo "Missing $ENV_FILE" >&2
        exit 1
    }
    # shellcheck disable=SC1090
    . "$ENV_FILE"
else
    [ -r /lib/functions.sh ] || {
        echo "No OpenWrt UCI loader and no ENV_FILE" >&2
        exit 1
    }
    # shellcheck disable=SC1091
    . /lib/functions.sh
    COUNTRIES=''
    ASNS=''
    add_country() { COUNTRIES="${COUNTRIES:+$COUNTRIES }$1"; }
    add_asn() { ASNS="${ASNS:+$ASNS }$1"; }
    config_load update_ipsets
    config_list_foreach main country add_country
    config_list_foreach main asn add_asn
    config_get DIR main dir /etc/ipsets
    config_get STATIC_NAME main static_name main.txt
    config_get OUT_NAME main out_name direct.txt
    config_get IPINFO_URL main ipinfo_url
    config_get IPVERSE_ASN_URL main ipverse_asn_url
    config_get CIDR_OVER_COVERAGE main cidr_over_coverage
    config_get CONNECT_TIMEOUT main connect_timeout 10
    config_get MAX_TIME main max_time 180
    config_get RETRY main retry 3
fi

SCRIPT_NAME="${0##*/}"
TAG="${SCRIPT_NAME%.sh}"

# Runtime settings come from UCI on OpenWrt or ENV_FILE on Linux.
# IPSETS_DIR and RELOAD_FIREWALL remain explicit generator/server/test overrides.
IPSETS_DIR="${IPSETS_DIR:-${DIR:-/etc/ipsets}}"
RELOAD_FIREWALL="${RELOAD_FIREWALL:-1}"

STATIC_NAME="${STATIC_NAME:-main.txt}"
OUT_NAME="${OUT_NAME:-direct.txt}"
STATIC_DIRECT_NAME="$STATIC_NAME"
OUT_DIRECT_NAME="$OUT_NAME"
IPINFO_URL="${IPINFO_URL:-https://github.com/Alice39s/"\
"ipinfo-csv-lite/releases/latest/download/ipinfo-lite.csv.gz}"
IPVERSE_ASN_URL="${IPVERSE_ASN_URL:-https://raw.githubusercontent.com/ipverse/as-ip-blocks/master}"
CIDR_OVER_COVERAGE="${CIDR_OVER_COVERAGE-}"

STATIC_DIRECT="$IPSETS_DIR/$STATIC_DIRECT_NAME"
OUT_DIRECT="$IPSETS_DIR/$OUT_DIRECT_NAME"
TMP_DIRECT="${OUT_DIRECT}.tmp"
TMP_OPTIMIZED="${TMP_DIRECT}.optimized"
TMP_IPINFO="/tmp/ipinfo-lite.$$.csv.gz"
TMP_COUNTRIES="/tmp/ipinfo-countries.$$.txt"

if [ "${COUNTRIES+x}" != "x" ]; then
    echo "ERROR: countries list is not configured" >&2
    exit 1
fi
if [ "${ASNS+x}" != "x" ]; then
    echo "ERROR: ASN list is not configured" >&2
    exit 1
fi
COUNTRIES="${COUNTRIES-}"
ASNS="${ASNS-}"

if [ -z "$CIDR_OVER_COVERAGE" ]; then
    echo "ERROR: cidr_over_coverage is empty" >&2
    exit 1
fi

CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-10}"
MAX_TIME="${MAX_TIME:-180}"
RETRY="${RETRY:-3}"

cleanup_tmp() {
    rm -f \
        "$TMP_DIRECT" "$TMP_OPTIMIZED" \
        "$TMP_IPINFO" "$TMP_COUNTRIES"
}

# main.txt is independent from the dynamic direct.txt file.
# Never append its contents to the dynamic list.

append_url_list() {
    url="$1"
    label="$2"

    data="$(
        curl -fsSL \
            --connect-timeout "$CONNECT_TIMEOUT" \
            --max-time "$MAX_TIME" \
            --retry "$RETRY" \
            "$url"
    )" || {
        logger -t "$TAG" "ERROR: failed to fetch $label from $url"
        return 1
    }

    lines="$(
        printf '%s\n' "$data" \
            | sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d'
    )"

    if [ -z "$lines" ]; then
        logger -t "$TAG" "ERROR: empty $label list from $url"
        return 1
    fi

    printf '%s\n' "$lines" >>"$TMP_DIRECT"
    logger -t "$TAG" "OK: fetched $label from $url"
    return 0
}

append_country_lists() {
    [ -n "$COUNTRIES" ] || return 0

    country_regex=""
    for country in $COUNTRIES; do
        case "$country" in
            [A-Za-z][A-Za-z]) ;;
            *)
                logger -t "$TAG" "ERROR: bad country code: $country"
                return 1
                ;;
        esac

        # shellcheck disable=SC2018 disable=SC2019
        country="$(printf '%s' "$country" | tr 'a-z' 'A-Z')"
        if [ -n "$country_regex" ]; then
            country_regex="$country_regex|"
        fi
        country_regex="$country_regex$country"
    done

    rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
    curl -fsSL \
        --connect-timeout "$CONNECT_TIMEOUT" \
        --max-time "$MAX_TIME" \
        --retry "$RETRY" \
        -o "$TMP_IPINFO" \
        "$IPINFO_URL" || {
        logger -t "$TAG" "ERROR: failed to fetch IPinfo Lite CSV"
        rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
        return 1
    }

    if [ ! -s "$TMP_IPINFO" ] || ! gzip -t "$TMP_IPINFO" 2>/dev/null; then
        logger -t "$TAG" "ERROR: invalid IPinfo Lite gzip archive"
        rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
        return 1
    fi

    gzip -dc "$TMP_IPINFO" \
        | grep -E "^[0-9.]+(/[0-9]+)?,(${country_regex})," \
        | cut -d, -f1 >"$TMP_COUNTRIES"

    if [ ! -s "$TMP_COUNTRIES" ]; then
        logger -t "$TAG" \
            "ERROR: no IPinfo CIDRs for countries: $COUNTRIES"
        rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
        return 1
    fi

    cat "$TMP_COUNTRIES" >>"$TMP_DIRECT"
    rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "OK: added IPinfo countries: $COUNTRIES"
    return 0
}

append_asn_lists() {
    for asn in $ASNS; do
        case "$asn" in
            '' | *[!0-9]*)
                logger -t "$TAG" "ERROR: bad ASN: $asn"
                return 1
                ;;
            *) ;;
        esac

        append_url_list \
            "$IPVERSE_ASN_URL/as/$asn/ipv4-aggregated.txt" \
            "as:$asn" || return 1
    done
}

optimize_direct() {
    if ! command -v cidr-squash >/dev/null 2>&1; then
        logger -t "$TAG" "ERROR: cidr-squash is not installed"
        return 1
    fi

    before="$(wc -l <"$TMP_DIRECT")"
    cidr-squash \
        -q \
        -p "$CIDR_OVER_COVERAGE" \
        "$TMP_DIRECT" >"$TMP_OPTIMIZED" || {
        logger -t "$TAG" "ERROR: cidr-squash optimization failed"
        return 1
    }

    if [ ! -s "$TMP_OPTIMIZED" ]; then
        logger -t "$TAG" "ERROR: cidr-squash generated an empty direct list"
        return 1
    fi

    after="$(wc -l <"$TMP_OPTIMIZED")"
    mv -f "$TMP_OPTIMIZED" "$TMP_DIRECT" || return 1
    logger -t "$TAG" \
        "OK: cidr-squash optimized direct list: $before -> $after entries"
}

reload_firewall_if_needed() {
    [ "$1" -eq 1 ] || return 0
    [ "$RELOAD_FIREWALL" = "1" ] || return 0

    if [ -x /etc/init.d/firewall ]; then
        /etc/init.d/firewall reload >/dev/null 2>&1 \
            || /etc/init.d/firewall restart >/dev/null 2>&1
    fi
}

mkdir -p "$IPSETS_DIR" || exit 1
cleanup_tmp

[ -s "$STATIC_DIRECT" ] || {
    logger -t "$TAG" "ERROR: missing or empty main list: $STATIC_DIRECT"
    exit 1
}

append_country_lists || {
    cleanup_tmp
    logger -t "$TAG" "ERROR: failed to build direct ipset"
    exit 1
}

append_asn_lists || {
    cleanup_tmp
    logger -t "$TAG" "ERROR: failed to build direct ipset"
    exit 1
}

if [ ! -s "$TMP_DIRECT" ]; then
    cleanup_tmp
    logger -t "$TAG" "ERROR: generated direct ipset is empty"
    exit 1
fi

optimize_direct || {
    cleanup_tmp
    logger -t "$TAG" "ERROR: failed to optimize direct list"
    exit 1
}

changed=0
if [ ! -f "$OUT_DIRECT" ] || ! cmp -s "$TMP_DIRECT" "$OUT_DIRECT"; then
    mv -f "$TMP_DIRECT" "$OUT_DIRECT" || {
        cleanup_tmp
        logger -t "$TAG" "ERROR: failed to replace $OUT_DIRECT"
        exit 1
    }
    changed=1
else
    rm -f "$TMP_DIRECT"
fi

cleanup_tmp
reload_firewall_if_needed "$changed"
logger -t "$TAG" "OK: direct ipset updated, changed=$changed"
