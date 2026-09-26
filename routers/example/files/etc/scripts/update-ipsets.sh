#!/bin/sh

ENV_FILE="${ENV_FILE:-/etc/router-autoinstall.env}"
if [ -r "$ENV_FILE" ]; then
    # Generated file, loaded once at startup. Re-run to apply changes.
    # shellcheck disable=SC1091 disable=SC1090
    . "$ENV_FILE"
fi

SCRIPT_NAME="${0##*/}"
TAG="${SCRIPT_NAME%.sh}"

# Runtime path/apply knobs may be overridden by the local generator.
IPSETS_DIR="${IPSETS_DIR:-/etc/ipsets}"
RELOAD_FIREWALL="${RELOAD_FIREWALL:-1}"

# These defaults are tied to this script's parsers/layouts. A different
# source format requires changing the parser together with the URL.
STATIC_DIRECT_NAME="direct-static.txt"
OUT_DIRECT_NAME="direct.txt"
IPINFO_LITE_CSV_GZ_URL="https://github.com/Alice39s/ipinfo-csv-lite/""\
releases/latest/download/ipinfo-lite.csv.gz"
URL_IPVERSE_ASN="https://raw.githubusercontent.com/ipverse/as-ip-blocks/master"

STATIC_DIRECT="$IPSETS_DIR/$STATIC_DIRECT_NAME"
OUT_DIRECT="$IPSETS_DIR/$OUT_DIRECT_NAME"
TMP_DIRECT="${OUT_DIRECT}.tmp"
TMP_SORTED="${TMP_DIRECT}.sorted"
TMP_IPINFO="/tmp/ipinfo-lite.$$.csv.gz"
TMP_COUNTRIES="/tmp/ipinfo-countries.$$.txt"

DIRECT_COUNTRIES="${DIRECT_COUNTRIES:-ru cn by}"
DIRECT_ASNS="${DIRECT_ASNS:-32590}"

UPDATE_IPSETS_CURL_CONNECT_TIMEOUT=10
UPDATE_IPSETS_CURL_MAX_TIME=180
UPDATE_IPSETS_CURL_RETRY=3

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
            --connect-timeout "$UPDATE_IPSETS_CURL_CONNECT_TIMEOUT" \
            --max-time "$UPDATE_IPSETS_CURL_MAX_TIME" \
            --retry "$UPDATE_IPSETS_CURL_RETRY" \
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
    [ -n "$DIRECT_COUNTRIES" ] || return 0

    country_regex=""
    for country in $DIRECT_COUNTRIES; do
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
        --connect-timeout "$UPDATE_IPSETS_CURL_CONNECT_TIMEOUT" \
        --max-time "$UPDATE_IPSETS_CURL_MAX_TIME" \
        --retry "$UPDATE_IPSETS_CURL_RETRY" \
        -o "$TMP_IPINFO" \
        "$IPINFO_LITE_CSV_GZ_URL" || {
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
        | grep -E "^[0-9.]+/[0-9]+,(${country_regex})," \
        | cut -d, -f1 >"$TMP_COUNTRIES"

    if [ ! -s "$TMP_COUNTRIES" ]; then
        logger -t "$TAG" \
            "ERROR: no IPinfo CIDRs for countries: $DIRECT_COUNTRIES"
        rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
        return 1
    fi

    cat "$TMP_COUNTRIES" >>"$TMP_DIRECT"
    rm -f "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "OK: added IPinfo countries: $DIRECT_COUNTRIES"
    return 0
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
    [ "$RELOAD_FIREWALL" = "1" ] || return 0

    if [ -x /etc/init.d/firewall ]; then
        /etc/init.d/firewall reload >/dev/null 2>&1 \
            || /etc/init.d/firewall restart >/dev/null 2>&1
    fi
}

mkdir -p "$IPSETS_DIR" || exit 1
rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"

append_static_direct || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
    exit 1
}

append_country_lists || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "ERROR: failed to build direct ipset"
    exit 1
}

append_asn_lists || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "ERROR: failed to build direct ipset"
    exit 1
}

if [ ! -s "$TMP_DIRECT" ]; then
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "ERROR: generated direct ipset is empty"
    exit 1
fi

LC_ALL=C sort -u "$TMP_DIRECT" >"$TMP_SORTED" || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "ERROR: failed to sort direct list"
    exit 1
}

mv -f "$TMP_SORTED" "$TMP_DIRECT" || {
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
    logger -t "$TAG" "ERROR: failed to replace sorted tmp direct list"
    exit 1
}

changed=0
if [ ! -f "$OUT_DIRECT" ] || ! cmp -s "$TMP_DIRECT" "$OUT_DIRECT"; then
    mv -f "$TMP_DIRECT" "$OUT_DIRECT" || {
        rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
        logger -t "$TAG" "ERROR: failed to replace $OUT_DIRECT"
        exit 1
    }
    changed=1
else
    rm -f "$TMP_DIRECT" "$TMP_SORTED" "$TMP_IPINFO" "$TMP_COUNTRIES"
fi

reload_firewall_if_needed "$changed"
logger -t "$TAG" "OK: direct ipset updated, changed=$changed"
