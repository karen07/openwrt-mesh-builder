#!/bin/sh

if [ -r /etc/router-autoinstall.env ]; then
    # Generated file, loaded once at startup. Re-run to apply changes.
    # shellcheck disable=SC1091
    . /etc/router-autoinstall.env
fi

SCRIPT_NAME="${0##*/}"
TAG="${SCRIPT_NAME%.sh}"
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

CURL_CONNECT_TIMEOUT="${UPDATE_IPSETS_CURL_CONNECT_TIMEOUT:-10}"
CURL_MAX_TIME="${UPDATE_IPSETS_CURL_MAX_TIME:-60}"
CURL_RETRY="${UPDATE_IPSETS_CURL_RETRY:-3}"

append_static_direct() {
    if [ ! -s "$STATIC_DIRECT" ]; then
        logger -t "$TAG" "ERROR: missing or empty static direct list: $STATIC_DIRECT"
        return 1
    fi

    sed '/^[[:space:]]*#/d; /^[[:space:]]*$/d' "$STATIC_DIRECT" >>"$TMP_DIRECT"
}

append_url_list() {
    url="$1"
    label="$2"

    data="$(
        curl -fsSL \
            --connect-timeout "$CURL_CONNECT_TIMEOUT" \
            --max-time "$CURL_MAX_TIME" \
            --retry "$CURL_RETRY" \
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
    for country in $DIRECT_COUNTRIES; do
        case "$country" in
            [a-z][a-z]) ;;
            *)
                logger -t "$TAG" "ERROR: bad country code: $country"
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
                logger -t "$TAG" "ERROR: bad ASN: $asn"
                return 1
                ;;
            *) ;;
        esac

        append_url_list \
            "$URL_IPVERSE_ASN/as/$asn/ipv4-aggregated.txt" \
            "as:$asn" || return 1
    done
}

reload_firewall_if_needed() {
    [ "$1" -eq 1 ] || return 0

    if [ -x /etc/init.d/firewall ]; then
        /etc/init.d/firewall reload >/dev/null 2>&1 \
            || /etc/init.d/firewall restart >/dev/null 2>&1
    fi
}

mkdir -p "$IPSETS_DIR" || exit 1
rm -f "$TMP_DIRECT" "$TMP_SORTED"

append_static_direct || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
    exit 1
}

append_country_lists || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
    logger -t "$TAG" "ERROR: failed to build direct ipset"
    exit 1
}

append_asn_lists || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
    logger -t "$TAG" "ERROR: failed to build direct ipset"
    exit 1
}

if [ ! -s "$TMP_DIRECT" ]; then
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
    logger -t "$TAG" "ERROR: generated direct ipset is empty"
    exit 1
fi

sort -u "$TMP_DIRECT" >"$TMP_SORTED" || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
    logger -t "$TAG" "ERROR: failed to sort direct list"
    exit 1
}

mv -f "$TMP_SORTED" "$TMP_DIRECT" || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
    logger -t "$TAG" "ERROR: failed to replace sorted tmp direct list"
    exit 1
}

changed=0
if [ ! -f "$OUT_DIRECT" ] || ! cmp -s "$TMP_DIRECT" "$OUT_DIRECT"; then
    mv -f "$TMP_DIRECT" "$OUT_DIRECT" || {
        rm -f "$TMP_DIRECT" "$TMP_SORTED"
        logger -t "$TAG" "ERROR: failed to replace $OUT_DIRECT"
        exit 1
    }
    changed=1
else
    rm -f "$TMP_DIRECT" "$TMP_SORTED"
fi

reload_firewall_if_needed "$changed"
logger -t "$TAG" "OK: direct ipset updated, changed=$changed"
