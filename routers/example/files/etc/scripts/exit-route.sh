#!/bin/sh

# All persistent state, exit metadata and device policies are in exit_route.
# Routing and firewall changes use UCI; ip is used only to inspect Babel routes.
# shellcheck disable=SC1091
. /lib/functions.sh
LOCK_FILE=/tmp/exit-route-control.lock
STATUS_FILE=/tmp/exit-route.status
NETWORK_PENDING_FILE=/tmp/exit-route-network.pending
FIREWALL_PENDING_FILE=/tmp/exit-route-firewall.pending
FIREWALL_DIRTY=0
NETWORK_DIRTY=0
TABLE=''
INTERVAL=5
BASE_TARGETS=''
EXIT_NAMES=''
EXIT_DATA=''
ROUTE_SECTION=''

append_base() { BASE_TARGETS="${BASE_TARGETS:+$BASE_TARGETS }$1"; }
collect_exit() {
    collect_exit_prefix=''
    collect_exit_policy=''
    collect_exit_interface=''
    config_get collect_exit_prefix "$1" prefix
    config_get collect_exit_policy "$1" policy
    config_get collect_exit_interface "$1" interface
    [ -n "$collect_exit_prefix" ] && [ -n "$collect_exit_policy" ] \
        && [ -n "$collect_exit_interface" ] || return 1
    EXIT_NAMES="${EXIT_NAMES:+$EXIT_NAMES }$1"
    EXIT_DATA="${EXIT_DATA}${EXIT_DATA:+
}$1:$collect_exit_prefix:$collect_exit_policy:$collect_exit_interface"
}

# Reject outdated and misspelled UCI options before changing routes or firewall.
# UCI's own syntax is accepted; only the current exit_route keys are allowed.
validate_exit_uci_keys() {
    validate_exit_uci_dump="$(uci -q show exit_route)" || {
        echo 'Unable to read exit_route UCI configuration' >&2
        return 1
    }
    [ -n "$validate_exit_uci_dump" ] || {
        echo 'Empty exit_route UCI configuration' >&2
        return 1
    }
    while IFS= read -r validate_exit_uci_line || [ -n "$validate_exit_uci_line" ]; do
        validate_exit_uci_ref="${validate_exit_uci_line%%=*}"
        validate_exit_uci_value="${validate_exit_uci_line#*=}"
        case "$validate_exit_uci_ref" in
            exit_route.*) : ;;
            *)
                echo "Unexpected UCI record: $validate_exit_uci_ref" >&2
                return 1
                ;;
        esac
        validate_exit_uci_path="${validate_exit_uci_ref#exit_route.}"
        case "$validate_exit_uci_path" in
            *.*)
                validate_exit_uci_section="${validate_exit_uci_path%%.*}"
                validate_exit_uci_option="${validate_exit_uci_path#*.}"
                validate_exit_uci_kind="$(uci -q get "exit_route.$validate_exit_uci_section")" || {
                    echo "Invalid EXIT section: $validate_exit_uci_section" >&2
                    return 1
                }
                case "$validate_exit_uci_kind:$validate_exit_uci_option" in
                    state:table | state:interval | state:mode | state:exit | \
                        state:base_auto_exit | state:auto_exit | \
                        exit:prefix | exit:policy | exit:interface | \
                        device:ip | device:mode | device:exit | device:auto_exit | device:disabled)
                        :
                        ;;
                    *)
                        echo "Unsupported exit_route option: $validate_exit_uci_path" >&2
                        return 1
                        ;;
                esac
                if [ "$validate_exit_uci_kind" = state ] \
                    && [ "$validate_exit_uci_section" != main ]; then
                    echo "Unsupported state section: $validate_exit_uci_section" >&2
                    return 1
                fi
                ;;
            *)
                case "$validate_exit_uci_value:$validate_exit_uci_path" in
                    state:main | exit:* | device:@device\[*\]) : ;;
                    *)
                        echo "Unsupported exit_route section: $validate_exit_uci_path" >&2
                        return 1
                        ;;
                esac
                ;;
        esac
    done <<EOF
$validate_exit_uci_dump
EOF
    [ "$(uci -q get exit_route.main)" = state ] || {
        echo "Missing exit_route main state" >&2
        return 1
    }
}

load_exit_config() {
    TABLE=''
    INTERVAL=5
    BASE_TARGETS=''
    EXIT_NAMES=''
    EXIT_DATA=''
    validate_exit_uci_keys || return 1
    config_load exit_route || return 1
    config_get TABLE main table
    config_get INTERVAL main interval 5
    config_list_foreach main base_auto_exit append_base
    config_foreach collect_exit exit
    case "$TABLE" in
        '' | *[!0-9]* | 0)
            echo 'Invalid exit-route table' >&2
            return 1
            ;;
        *) : ;;
    esac
    case "$INTERVAL" in
        '' | *[!0-9]* | 0)
            echo 'Invalid exit-route interval' >&2
            return 1
            ;;
        *) : ;;
    esac
    [ -n "$BASE_TARGETS" ] && [ -n "$EXIT_NAMES" ] || {
        echo 'Missing exit-route base_auto_exit or exit definitions' >&2
        return 1
    }
    ROUTE_SECTION="exit${TABLE}"
}

known_exit() {
    case " $EXIT_NAMES " in
        *" $1 "*) return 0 ;;
        *) return 1 ;;
    esac
}

exit_field() {
    printf '%s\n' "$EXIT_DATA" | awk -F: -v name="$1" -v field="$2" \
        '$1 == name { print $field; exit }'
}

valid_auto_targets() {
    valid_auto_targets_seen=''
    valid_auto_targets_candidate=''
    for valid_auto_targets_candidate in $1; do
        known_exit "$valid_auto_targets_candidate" || return 1
        case " $valid_auto_targets_seen " in
            *" $valid_auto_targets_candidate "*) return 1 ;;
            *)
                valid_auto_targets_seen="${valid_auto_targets_seen:+$valid_auto_targets_seen }"
                valid_auto_targets_seen="$valid_auto_targets_seen$valid_auto_targets_candidate"
                ;;
        esac
    done
    [ -n "$valid_auto_targets_seen" ]
}

load_auto_targets() {
    TARGETS="$(uci -q get exit_route.main.auto_exit || true)"
    [ -n "$TARGETS" ] || TARGETS="$BASE_TARGETS"
    valid_auto_targets "$TARGETS"
}

# A device-specific list overrides the shared AUTO order only for that device.
# Without auto_exit, a device continues to inherit main.auto_exit.
device_auto_targets() {
    device_auto_targets_value="$(uci -q get "exit_route.$1.auto_exit" || true)"
    [ -n "$device_auto_targets_value" ] || device_auto_targets_value="$TARGETS"
    valid_auto_targets "$device_auto_targets_value" || return 1
    printf '%s\n' "$device_auto_targets_value"
}

has_babel_target() {
    has_babel_target_prefix=''
    has_babel_target_prefix="$(exit_field "$1" 2)"
    # Dynamic Babel reachability cannot be obtained from static UCI data.
    [ -n "$has_babel_target_prefix" ] \
        && ip -4 route show "$has_babel_target_prefix" proto babel 2>/dev/null \
        | grep -q .
}

best_available() {
    best_available_candidate=''
    for best_available_candidate in ${1:-$TARGETS}; do
        if has_babel_target "$best_available_candidate"; then
            printf '%s\n' "$best_available_candidate"
            return 0
        fi
    done
    return 1
}

current_mode() {
    current_mode_mode="$(uci -q get exit_route.main.mode || true)"
    case "$current_mode_mode" in
        AUTO | DIRECT | SPLIT_FAIL_OPEN | SPLIT_FAIL_CLOSED | EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
            printf '%s\n' "$current_mode_mode"
            ;;
        *)
            echo "Invalid global mode: $current_mode_mode" >&2
            return 1
            ;;
    esac
}

# The generator owns the route section and all static routing parameters.
# Never create or repair it in runtime: an incomplete deployment is an error.
require_network_route() {
    [ "$(uci -q get "network.$ROUTE_SECTION" || true)" = route ] \
        && [ "$(uci -q get "network.$ROUTE_SECTION.table" || true)" = "$TABLE" ] \
        && [ "$(uci -q get "network.$ROUTE_SECTION.target" || true)" = 0.0.0.0/0 ] || {
        echo "Missing or invalid generated network route: $ROUTE_SECTION" >&2
        return 1
    }
}

current_target() {
    current_target_iface=''
    current_target_candidate=''
    if [ "$(uci -q get "network.$ROUTE_SECTION.disabled" || true)" = 1 ]; then
        echo DISABLED
        return
    fi
    current_target_iface="$(uci -q get "network.$ROUTE_SECTION.interface" || true)"
    for current_target_candidate in $EXIT_NAMES; do
        [ "$current_target_iface" = "$(exit_field "$current_target_candidate" 4)" ] && {
            echo "$current_target_candidate"
            return
        }
    done
    echo OTHER
}

set_network_route() {
    set_network_route_target=''
    set_network_route_interface=''
    set_network_route_target="$1"
    if [ -z "$set_network_route_target" ]; then
        # Keep the generated interface while disabled for a smaller UCI diff.
        uci -q set "network.$ROUTE_SECTION.disabled=1" || return 1
    else
        set_network_route_interface="$(exit_field "$set_network_route_target" 4)"
        [ -n "$set_network_route_interface" ] || return 1
        uci -q set "network.$ROUTE_SECTION.interface=$set_network_route_interface" || return 1
        uci -q delete "network.$ROUTE_SECTION.disabled" || true
    fi
    NETWORK_DIRTY=1
}

valid_ip() {
    valid_ip_old_ifs=''
    valid_ip_octet=''
    case "$1" in
        '' | *[!0-9.]* | *..* | .* | *.) return 1 ;;
        *) : ;;
    esac
    valid_ip_old_ifs="$IFS"
    IFS=.
    # shellcheck disable=SC2086
    set -- $1
    IFS="$valid_ip_old_ifs"
    [ "$#" -eq 4 ] || return 1
    for valid_ip_octet; do
        [ -n "$valid_ip_octet" ] && [ "${#valid_ip_octet}" -le 3 ] || return 1
        case "$valid_ip_octet" in
            0 | [1-9] | [1-9][0-9] | [1-9][0-9][0-9]) ;;
            *) return 1 ;;
        esac
        [ "$valid_ip_octet" -le 255 ] || return 1
    done
    [ "$1" -gt 0 ] && [ "$1" -ne 127 ] && [ "$1" -lt 224 ]
}

firewall_stem_for_ip() {
    printf 'exit_route_dev_%s\n' "$(printf '%s' "$1" | tr . _)"
}

list_device_sections() {
    uci -q show exit_route | sed -n 's/^exit_route\.\([^.=]*\)=device$/\1/p'
}

set_fw_option() {
    set_fw_option_ref=''
    set_fw_option_key=''
    set_fw_option_val=''
    set_fw_option_ref="$1"
    set_fw_option_key="$2"
    set_fw_option_val="$3"
    if [ "$(uci -q get "$set_fw_option_ref.$set_fw_option_key" || true)" \
        != "$set_fw_option_val" ]; then
        uci -q set "$set_fw_option_ref.$set_fw_option_key=$set_fw_option_val" || return 1
        FIREWALL_DIRTY=1
    fi
}

del_fw_option() {
    if uci -q get "$1.$2" >/dev/null 2>&1; then
        uci -q delete "$1.$2" || return 1
        FIREWALL_DIRTY=1
    fi
}

# Locate an anonymous firewall rule by its stable option name.
find_fw_rule() {
    uci -q show firewall | sed -n \
        "s/^firewall\.\([^.=]*\)\.name='$1'$/firewall.\1/p" | head -n 1
}

remove_fw_section() {
    remove_fw_section_ref=''
    remove_fw_section_ref="$(find_fw_rule "ExitRoute-$1")"
    if [ -n "$remove_fw_section_ref" ]; then
        uci -q delete "$remove_fw_section_ref" || return 1
        FIREWALL_DIRTY=1
    fi
}

# Common attributes for the three device rule types. Keep the reference in
# FW_RULE_REF: a command substitution would lose FIREWALL_DIRTY in a subshell.
ensure_device_rule_base() {
    ensure_device_rule_base_name="$1"
    ensure_device_rule_base_ip="$2"
    FW_RULE_REF="$(find_fw_rule "ExitRoute-$ensure_device_rule_base_name")"
    if [ -z "$FW_RULE_REF" ]; then
        ensure_device_rule_base_created="$(uci -q add firewall rule)" || return 1
        [ -n "$ensure_device_rule_base_created" ] || return 1
        FW_RULE_REF="firewall.$ensure_device_rule_base_created"
        FIREWALL_DIRTY=1
    fi
    set_fw_option "$FW_RULE_REF" name "ExitRoute-$ensure_device_rule_base_name" || return 1
    set_fw_option "$FW_RULE_REF" src lan || return 1
    set_fw_option "$FW_RULE_REF" src_ip "$ensure_device_rule_base_ip" || return 1
    set_fw_option "$FW_RULE_REF" dest '*' || return 1
    set_fw_option "$FW_RULE_REF" family ipv4 || return 1
    set_fw_option "$FW_RULE_REF" proto all || return 1
    del_fw_option "$FW_RULE_REF" enabled || return 1
}

# Device MARK overrides the global policy for this source.
ensure_fw_rule() {
    ensure_device_rule_base "$1" "$2" || return 1
    set_fw_option "$FW_RULE_REF" target MARK || return 1
    set_fw_option "$FW_RULE_REF" set_mark "$3" || return 1
    del_fw_option "$FW_RULE_REF" mark || return 1
    if [ -n "$4" ]; then
        set_fw_option "$FW_RULE_REF" ipset "$4" || return 1
    else
        del_fw_option "$FW_RULE_REF" ipset || return 1
    fi
}

ensure_fw_drop() {
    ensure_device_rule_base "$1" "$2" || return 1
    set_fw_option "$FW_RULE_REF" target DROP || return 1
    set_fw_option "$FW_RULE_REF" mark "$3" || return 1
    set_fw_option "$FW_RULE_REF" ipset direct || return 1
    del_fw_option "$FW_RULE_REF" set_mark || return 1
}

# Unavailable fixed EXIT must block all device traffic outside main.
ensure_fw_block() {
    ensure_device_rule_base "$1" "$2" || return 1
    set_fw_option "$FW_RULE_REF" target DROP || return 1
    set_fw_option "$FW_RULE_REF" ipset '!main' || return 1
    if [ -n "$3" ]; then
        set_fw_option "$FW_RULE_REF" mark "$3" || return 1
    else
        del_fw_option "$FW_RULE_REF" mark || return 1
    fi
    del_fw_option "$FW_RULE_REF" set_mark || return 1
}

# Even if the selected IPIP default route disappears while the Babel marker
# remains visible, a strict client's traffic may not escape via the WAN zone.
ensure_fw_wan_guard() {
    ensure_device_rule_base "$1" "$2" || return 1
    set_fw_option "$FW_RULE_REF" dest wan || return 1
    set_fw_option "$FW_RULE_REF" target DROP || return 1
    set_fw_option "$FW_RULE_REF" mark "$3" || return 1
    del_fw_option "$FW_RULE_REF" ipset || return 1
    del_fw_option "$FW_RULE_REF" set_mark || return 1
}

sync_global_firewall() {
    sync_global_firewall_mode="$1"
    sync_global_firewall_target="$2"
    for sync_global_firewall_zone in lan trustedaccess transitaccess; do
        case "$sync_global_firewall_zone" in
            lan)
                sync_global_firewall_rule_name=Exitlan
                sync_global_firewall_drop_name=ExitRouteDirectDropLan
                sync_global_firewall_unavailable_name=ExitRouteUnavailableLan
                sync_global_firewall_guard_name=ExitRouteWanGuardLan
                ;;
            trustedaccess)
                sync_global_firewall_rule_name=ExitTrustedAccess
                sync_global_firewall_drop_name=ExitRouteDirectDropTrustedAccess
                sync_global_firewall_unavailable_name=ExitRouteUnavailableTrustedAccess
                sync_global_firewall_guard_name=ExitRouteWanGuardTrustedAccess
                ;;
            transitaccess)
                sync_global_firewall_rule_name=ExitTransitAccess
                sync_global_firewall_drop_name=ExitRouteDirectDropTransitAccess
                sync_global_firewall_unavailable_name=ExitRouteUnavailableTransitAccess
                sync_global_firewall_guard_name=ExitRouteWanGuardTransitAccess
                ;;
            *) return 1 ;;
        esac
        sync_global_firewall_ref="$(find_fw_rule "$sync_global_firewall_rule_name")"
        if [ -z "$sync_global_firewall_ref" ]; then
            [ "$sync_global_firewall_zone" = lan ] && return 1
            continue
        fi
        # EXIT_FAIL_OPEN keeps the mark even without a Babel route:
        # direct destinations must still be dropped during WAN fallback.
        case "$sync_global_firewall_mode" in
            DIRECT) sync_global_firewall_mark=0 ;;
            AUTO | SPLIT_FAIL_OPEN)
                if [ -n "$sync_global_firewall_target" ]; then
                    sync_global_firewall_mark=1
                else
                    sync_global_firewall_mark=0
                fi
                ;;
            SPLIT_FAIL_CLOSED | EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED) sync_global_firewall_mark=1 ;;
            *) return 1 ;;
        esac
        if [ "$sync_global_firewall_mark" = 1 ]; then
            del_fw_option "$sync_global_firewall_ref" enabled || return 1
        else
            set_fw_option "$sync_global_firewall_ref" enabled 0 || return 1
        fi
        case "$sync_global_firewall_mode" in
            EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
                del_fw_option "$sync_global_firewall_ref" ipset || return 1
                ;;
            *) set_fw_option "$sync_global_firewall_ref" ipset '!direct' || return 1 ;;
        esac
        sync_global_firewall_ref="$(find_fw_rule "$sync_global_firewall_drop_name")"
        [ -n "$sync_global_firewall_ref" ] || return 1
        case "$sync_global_firewall_mode" in
            EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
                del_fw_option "$sync_global_firewall_ref" enabled || return 1
                ;;
            *) set_fw_option "$sync_global_firewall_ref" enabled 0 || return 1 ;;
        esac
        sync_global_firewall_ref="$(find_fw_rule "$sync_global_firewall_unavailable_name")"
        [ -n "$sync_global_firewall_ref" ] || return 1
        case "$sync_global_firewall_mode" in
            SPLIT_FAIL_CLOSED | EXIT_FAIL_CLOSED)
                if [ -z "$sync_global_firewall_target" ]; then
                    del_fw_option "$sync_global_firewall_ref" enabled || return 1
                else
                    set_fw_option "$sync_global_firewall_ref" enabled 0 || return 1
                fi
                ;;
            *) set_fw_option "$sync_global_firewall_ref" enabled 0 || return 1 ;;
        esac
        sync_global_firewall_ref="$(find_fw_rule "$sync_global_firewall_guard_name")"
        [ -n "$sync_global_firewall_ref" ] || return 1
        case "$sync_global_firewall_mode" in
            SPLIT_FAIL_CLOSED | EXIT_FAIL_CLOSED)
                del_fw_option "$sync_global_firewall_ref" enabled || return 1
                ;;
            *) set_fw_option "$sync_global_firewall_ref" enabled 0 || return 1 ;;
        esac
    done
}

sync_device_firewall() {
    sync_device_firewall_section="$1"
    sync_device_firewall_src_ip="$2"
    sync_device_firewall_mode="$(
        uci -q get "exit_route.$sync_device_firewall_section.mode" || true
    )"
    sync_device_firewall_requested="$(
        uci -q get "exit_route.$sync_device_firewall_section.exit" || true
    )"
    sync_device_firewall_selected="$sync_device_firewall_requested"
    sync_device_firewall_policy=''
    valid_ip "$sync_device_firewall_src_ip" || return 1
    case "$sync_device_firewall_mode" in
        DEFAULT | DIRECT) : ;;
        AUTO)
            sync_device_firewall_targets="$(
                device_auto_targets "$sync_device_firewall_section"
            )" || return 1
            sync_device_firewall_selected="$(
                best_available "$sync_device_firewall_targets" || true
            )"
            ;;
        SPLIT_FAIL_OPEN | SPLIT_FAIL_CLOSED | EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
            known_exit "$sync_device_firewall_selected" || return 1
            has_babel_target "$sync_device_firewall_selected" || sync_device_firewall_selected=''
            ;;
        *)
            echo "Invalid device mode: $sync_device_firewall_mode" >&2
            return 1
            ;;
    esac
    sync_device_firewall_stem="$(firewall_stem_for_ip "$sync_device_firewall_src_ip")"
    case "$sync_device_firewall_mode" in
        SPLIT_FAIL_CLOSED | EXIT_FAIL_CLOSED)
            sync_device_firewall_policy="$(exit_field "$sync_device_firewall_requested" 3)"
            if [ -z "$sync_device_firewall_selected" ]; then
                if [ "$sync_device_firewall_mode" = SPLIT_FAIL_CLOSED ]; then
                    ensure_fw_block "${sync_device_firewall_stem}_block" \
                        "$sync_device_firewall_src_ip" "$sync_device_firewall_policy" || return 1
                else
                    ensure_fw_block "${sync_device_firewall_stem}_block" \
                        "$sync_device_firewall_src_ip" '' || return 1
                fi
            else
                remove_fw_section "${sync_device_firewall_stem}_block" || return 1
            fi
            ensure_fw_wan_guard "${sync_device_firewall_stem}_guard" \
                "$sync_device_firewall_src_ip" "$sync_device_firewall_policy" || return 1
            ;;
        *)
            remove_fw_section "${sync_device_firewall_stem}_block" || return 1
            remove_fw_section "${sync_device_firewall_stem}_guard" || return 1
            ;;
    esac
    case "$sync_device_firewall_mode" in
        DEFAULT)
            remove_fw_section "${sync_device_firewall_stem}_direct" || return 1
            remove_fw_section "${sync_device_firewall_stem}_exit" || return 1
            remove_fw_section "${sync_device_firewall_stem}_drop" || return 1
            ;;
        DIRECT)
            remove_fw_section "${sync_device_firewall_stem}_direct" || return 1
            remove_fw_section "${sync_device_firewall_stem}_drop" || return 1
            ensure_fw_rule "${sync_device_firewall_stem}_exit" \
                "$sync_device_firewall_src_ip" 9999 '' || return 1
            ;;
        AUTO | SPLIT_FAIL_OPEN | SPLIT_FAIL_CLOSED | EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
            case "$sync_device_firewall_mode" in
                EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
                    remove_fw_section "${sync_device_firewall_stem}_direct" || return 1
                    if [ "$sync_device_firewall_mode" = EXIT_FAIL_OPEN ] \
                        && [ -z "$sync_device_firewall_selected" ]; then
                        # EXIT_FAIL_OPEN permits WAN fallback, but still drops direct.
                        sync_device_firewall_policy=9999
                    else
                        sync_device_firewall_policy="$(
                            exit_field "$sync_device_firewall_requested" 3
                        )"
                    fi
                    ensure_fw_rule "${sync_device_firewall_stem}_exit" \
                        "$sync_device_firewall_src_ip" "$sync_device_firewall_policy" '' || return 1
                    ensure_fw_drop "${sync_device_firewall_stem}_drop" \
                        "$sync_device_firewall_src_ip" "$sync_device_firewall_policy" || return 1
                    ;;
                *)
                    remove_fw_section "${sync_device_firewall_stem}_drop" || return 1
                    if [ -z "$sync_device_firewall_selected" ] \
                        && [ "$sync_device_firewall_mode" != SPLIT_FAIL_CLOSED ]; then
                        remove_fw_section "${sync_device_firewall_stem}_direct" || return 1
                        ensure_fw_rule "${sync_device_firewall_stem}_exit" \
                            "$sync_device_firewall_src_ip" 9999 '' || return 1
                    else
                        ensure_fw_rule "${sync_device_firewall_stem}_direct" \
                            "$sync_device_firewall_src_ip" 9999 direct || return 1
                        case "$sync_device_firewall_mode" in
                            SPLIT_FAIL_CLOSED)
                                sync_device_firewall_policy="$(
                                    exit_field "$sync_device_firewall_requested" 3
                                )"
                                ;;
                            *)
                                sync_device_firewall_policy="$(
                                    exit_field "$sync_device_firewall_selected" 3
                                )"
                                ;;
                        esac
                        ensure_fw_rule "${sync_device_firewall_stem}_exit" \
                            "$sync_device_firewall_src_ip" \
                            "$sync_device_firewall_policy" '!direct' || return 1
                    fi
                    ;;
            esac
            ;;
        *) return 1 ;;
    esac
}

validate_devices() {
    validate_devices_seen_ips=''
    validate_devices_section=''
    validate_devices_src_ip=''
    validate_devices_device_mode=''
    validate_devices_device_exit=''
    validate_devices_device_targets=''
    device_sections="$(list_device_sections)"
    validate_devices_seen_ips=''
    for validate_devices_section in $device_sections; do
        validate_devices_src_ip="$(uci -q get "exit_route.$validate_devices_section.ip" || true)"
        valid_ip "$validate_devices_src_ip" || {
            echo "Invalid device IPv4 address in section: $validate_devices_section" >&2
            return 1
        }
        case " $validate_devices_seen_ips " in
            *" $validate_devices_src_ip "*)
                echo "Duplicate device IPv4 address: $validate_devices_src_ip" >&2
                return 1
                ;;
            *)
                if [ -n "$validate_devices_seen_ips" ]; then
                    validate_devices_seen_ips="$validate_devices_seen_ips "
                fi
                validate_devices_seen_ips="$validate_devices_seen_ips$validate_devices_src_ip"
                ;;
        esac
        validate_devices_disabled="$(
            uci -q get "exit_route.$validate_devices_section.disabled" || true
        )"
        case "$validate_devices_disabled" in
            '' | 0 | 1) : ;;
            *)
                echo "Invalid disabled flag for device: $validate_devices_src_ip" >&2
                return 1
                ;;
        esac
        validate_devices_device_mode="$(
            uci -q get "exit_route.$validate_devices_section.mode" || true
        )"
        case "$validate_devices_device_mode" in
            DEFAULT | DIRECT) : ;;
            AUTO)
                validate_devices_device_targets="$(
                    uci -q get "exit_route.$validate_devices_section.auto_exit" || true
                )"
                if [ -n "$validate_devices_device_targets" ]; then
                    valid_auto_targets "$validate_devices_device_targets" || {
                        echo "Invalid AUTO order for device: $validate_devices_src_ip" >&2
                        return 1
                    }
                fi
                ;;
            SPLIT_FAIL_OPEN | SPLIT_FAIL_CLOSED | EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
                validate_devices_device_exit="$(
                    uci -q get "exit_route.$validate_devices_section.exit" || true
                )"
                known_exit "$validate_devices_device_exit" || {
                    echo "Invalid exit for device: $validate_devices_src_ip" >&2
                    return 1
                }
                ;;
            *)
                echo "Invalid mode for device: $validate_devices_src_ip" >&2
                return 1
                ;;
        esac
    done
}

sync_firewall() {
    sync_firewall_mode=''
    sync_firewall_target=''
    sync_firewall_desired=''
    sync_firewall_section=''
    sync_firewall_src_ip=''
    sync_firewall_stem=''
    sync_firewall_pattern=''
    sync_firewall_rule_name=''
    sync_firewall_ref=''
    sync_firewall_main_refs=''
    sync_firewall_total=''
    sync_firewall_count=''
    sync_firewall_tail_refs=''
    sync_firewall_mode="$1"
    sync_firewall_target="$2"
    FIREWALL_DIRTY=0
    sync_global_firewall "$sync_firewall_mode" "$sync_firewall_target" || return 1
    sync_firewall_desired=''
    for sync_firewall_section in $device_sections; do
        # Disabled overrides fall back to global routing. Their old managed
        # firewall rules are omitted from desired and removed below.
        [ "$(uci -q get "exit_route.$sync_firewall_section.disabled" || true)" = 1 ] && continue
        sync_firewall_src_ip="$(uci -q get "exit_route.$sync_firewall_section.ip")"
        sync_firewall_stem="$(firewall_stem_for_ip "$sync_firewall_src_ip")"
        sync_device_firewall "$sync_firewall_section" "$sync_firewall_src_ip" || return 1
        for sync_firewall_suffix in direct exit drop block guard; do
            sync_firewall_desired="$sync_firewall_desired "
            sync_firewall_desired="$sync_firewall_desired${sync_firewall_stem}_"
            sync_firewall_desired="$sync_firewall_desired$sync_firewall_suffix"
        done
    done
    # Remove obsolete device overrides; never remove rules for other owners.
    sync_firewall_pattern="s/^firewall\.[^.=]*\.name='ExitRoute-\(exit_route_dev_[0-9_]*_"
    sync_firewall_pattern="$sync_firewall_pattern\(direct\|exit\|drop\|block\|guard\)\)'$/\1/p"
    for sync_firewall_section in $(uci -q show firewall | sed -n "$sync_firewall_pattern"); do
        case " $sync_firewall_desired " in
            *" $sync_firewall_section "*) : ;;
            *) remove_fw_section "$sync_firewall_section" || return 1 ;;
        esac
    done
    # Place main overrides after all global and individual MARK rules.
    # Reorder only when needed, so an unchanged cycle does not reload fw4.
    sync_firewall_main_refs=''
    for sync_firewall_rule_name in ExitRouteMainLan ExitRouteMainTrustedAccess \
        ExitRouteMainTransitAccess; do
        sync_firewall_ref="$(find_fw_rule "$sync_firewall_rule_name")"
        [ -n "$sync_firewall_ref" ] || continue
        sync_firewall_main_refs="${sync_firewall_main_refs:+$sync_firewall_main_refs }"
        sync_firewall_main_refs="$sync_firewall_main_refs$sync_firewall_ref"
    done
    [ -n "$sync_firewall_main_refs" ] || return 1
    sync_firewall_total="$(uci -q show firewall | grep -c '^firewall\.[^.=]*=' || true)"
    # Compare the ordered suffix of the firewall sections first.
    sync_firewall_count=0
    for sync_firewall_ref in $sync_firewall_main_refs; do
        sync_firewall_count=$((sync_firewall_count + 1))
    done
    sync_firewall_tail_refs="$(uci -q show firewall | sed -n \
        's/^firewall\.\([^.=]*\)=.*$/firewall.\1/p' | tail -n "$sync_firewall_count" \
        | tr '\n' ' ' | sed 's/ $//')"
    if [ "$sync_firewall_tail_refs" != "$sync_firewall_main_refs" ]; then
        for sync_firewall_rule_name in ExitRouteMainLan ExitRouteMainTrustedAccess \
            ExitRouteMainTransitAccess; do
            sync_firewall_ref="$(find_fw_rule "$sync_firewall_rule_name")"
            [ -n "$sync_firewall_ref" ] || continue
            uci -q reorder "$sync_firewall_ref=$((sync_firewall_total - 1))" || return 1
        done
        FIREWALL_DIRTY=1
    fi
    reload_firewall_if_needed
}

reload_firewall_if_needed() {
    # Mark pending before commit: even a crash between commit and reload
    # must not turn a failed apply into an unchanged, successful cycle.
    if [ "$FIREWALL_DIRTY" = 1 ]; then
        : >"$FIREWALL_PENDING_FILE" || return 1
    fi
    [ -f "$FIREWALL_PENDING_FILE" ] || return 0
    uci commit firewall || return 1
    /etc/init.d/firewall reload || return 1
    rm -f "$FIREWALL_PENDING_FILE"
}

reload_network_if_needed() {
    if [ "$NETWORK_DIRTY" = 1 ]; then
        : >"$NETWORK_PENDING_FILE" || return 1
    fi
    [ -f "$NETWORK_PENDING_FILE" ] || return 0
    uci commit network || return 1
    /etc/init.d/network reload || return 1
    rm -f "$NETWORK_PENDING_FILE"
}

save_apply_status() {
    save_apply_status_value="$(printf 'APPLY=%s\nERROR=%s' "$1" "$2")"
    if [ -r "$STATUS_FILE" ] \
        && [ "$(cat "$STATUS_FILE")" = "$save_apply_status_value" ]; then
        return 0
    fi
    save_apply_status_tmp="${STATUS_FILE}.$$"
    printf '%s\n' "$save_apply_status_value" >"$save_apply_status_tmp" || return 1
    mv -f "$save_apply_status_tmp" "$STATUS_FILE"
}

apply_all_inner() {
    apply_all_inner_mode=''
    apply_all_inner_selected=''
    apply_all_inner_guard=''
    apply_all_inner_section=''
    apply_all_inner_ref=''
    apply_all_inner_current=''
    APPLY_STAGE=configuration
    load_exit_config || return 1
    apply_all_inner_mode="$(current_mode)" || return 1
    load_auto_targets || {
        echo 'Invalid AUTO exit list' >&2
        return 1
    }
    validate_devices || return 1
    require_network_route || return 1
    case "$apply_all_inner_mode" in
        DIRECT) apply_all_inner_selected='' ;;
        AUTO) apply_all_inner_selected="$(best_available || true)" ;;
        SPLIT_FAIL_OPEN | SPLIT_FAIL_CLOSED | EXIT_FAIL_OPEN | EXIT_FAIL_CLOSED)
            apply_all_inner_selected="$(uci -q get exit_route.main.exit || true)"
            known_exit "$apply_all_inner_selected" || {
                echo "Invalid exit_route.main.exit: $apply_all_inner_selected" >&2
                return 1
            }
            has_babel_target "$apply_all_inner_selected" || apply_all_inner_selected=''
            ;;
        *)
            echo "Invalid global mode: $apply_all_inner_mode" >&2
            return 1
            ;;
    esac
    NETWORK_DIRTY=0
    # Find the generated anonymous DoH guard by its stable policy signature.
    apply_all_inner_guard=''
    for apply_all_inner_section in $(uci -q show network | sed -n \
        "s/^network\.\([^.=]*\)\.priority='91'$/\1/p"); do
        apply_all_inner_ref="network.$apply_all_inner_section"
        if [ "$(uci -q get "$apply_all_inner_ref.uidrange" || true)" = 4453 ] \
            && [ "$(uci -q get "$apply_all_inner_ref.action" || true)" = unreachable ]; then
            apply_all_inner_guard="$apply_all_inner_ref"
            break
        fi
    done
    if [ -z "$apply_all_inner_guard" ]; then
        echo "Missing network DoH fail-closed guard" >&2
        return 1
    fi
    if [ "$apply_all_inner_mode" = EXIT_FAIL_CLOSED ]; then
        if [ "$(uci -q get "$apply_all_inner_guard.disabled" || true)" = 1 ]; then
            uci -q delete "$apply_all_inner_guard.disabled" || return 1
            NETWORK_DIRTY=1
        fi
    elif [ "$(uci -q get "$apply_all_inner_guard.disabled" || true)" != 1 ]; then
        uci -q set "$apply_all_inner_guard.disabled=1" || return 1
        NETWORK_DIRTY=1
    fi
    apply_all_inner_current="$(current_target)"
    if [ -z "$apply_all_inner_selected" ]; then
        [ "$apply_all_inner_current" = DISABLED ] || set_network_route '' || return 1
    else
        [ "$apply_all_inner_current" = "$apply_all_inner_selected" ] \
            || set_network_route "$apply_all_inner_selected" || return 1
    fi
    APPLY_STAGE=network
    reload_network_if_needed || {
        echo 'EXIT apply: network reload failed' >&2
        return 1
    }
    APPLY_STAGE=firewall
    sync_firewall "$apply_all_inner_mode" "$apply_all_inner_selected" || {
        echo 'EXIT apply: firewall reload failed' >&2
        return 1
    }
}

apply_all() {
    apply_all_inner || {
        save_apply_status ERROR "${APPLY_STAGE:-reconcile}"
        return 1
    }
    save_apply_status OK none
}

status() {
    status_mode=''
    status_selected=''
    status_candidate=''
    status_up=''
    status_prefix=''
    status_route=''
    status_hop=''
    load_exit_config || return 1
    status_mode="$(current_mode)" || return 1
    load_auto_targets || return 1
    status_selected="$(uci -q get exit_route.main.exit || echo -)"
    printf 'MODE=%s\nSELECTED=%s\nACTIVE=%s\nAUTO_DEFAULT=%s\nAUTO_EFFECTIVE=%s\n' \
        "$status_mode" "$status_selected" "$(current_target)" "$BASE_TARGETS" "$TARGETS"
    if [ -f "$NETWORK_PENDING_FILE" ]; then
        printf 'APPLY=ERROR\nERROR=network\n'
    elif [ -f "$FIREWALL_PENDING_FILE" ]; then
        printf 'APPLY=ERROR\nERROR=firewall\n'
    elif [ -r "$STATUS_FILE" ]; then
        cat "$STATUS_FILE"
    else
        printf 'APPLY=UNKNOWN\nERROR=none\n'
    fi
    for status_candidate in $EXIT_NAMES; do
        status_prefix="$(exit_field "$status_candidate" 2)"
        status_route=''
        if [ -n "$status_prefix" ]; then
            status_route="$(ip -4 route show "$status_prefix" proto babel 2>/dev/null \
                | sed -n '1p')"
        fi
        if [ -n "$status_route" ]; then status_up=1; else status_up=0; fi
        printf 'EXIT\t%s\t%s\t%s\n' \
            "$status_candidate" "$status_up" "$(exit_field "$status_candidate" 3)"
        [ "$status_up" = 1 ] || continue
        # Show the installed first hop, not an unverified end-to-end mesh path.
        # The extra HOP record preserves the existing EXIT status contract.
        status_hop="$(printf '%s\n' "$status_route" | awk '
            {
                for (i = 1; i <= NF; i++) {
                    if ($i == "via" && i < NF) {
                        gateway = $(i + 1)
                        if (gateway == "inet6" && i + 2 <= NF) gateway = $(i + 2)
                    }
                    if ($i == "dev" && i < NF) device = $(i + 1)
                }
            }
            END { printf "%s\t%s", gateway ? gateway : "-", device ? device : "-" }
        ')"
        printf 'HOP\t%s\t%s\n' "$status_candidate" "$status_hop"
    done
}

locked() (
    exec 9>"$LOCK_FILE" || exit 1
    flock 9 || {
        echo 'exit-route lock failed' >&2
        exit 1
    }
    "$@"
)

case "${1:-run}" in
    status)
        [ "$#" -eq 1 ] || exit 2
        status
        ;;
    once)
        [ "$#" -eq 1 ] || exit 2
        locked apply_all
        ;;
    run)
        [ "$#" -le 1 ] || exit 2
        run_last_error=''
        while true; do
            if run_error="$(locked apply_all 2>&1)"; then
                run_last_error=''
            elif [ "$run_error" != "$run_last_error" ]; then
                printf '%s\n' "$run_error" >&2
                echo 'exit-route apply failed' >&2
                run_last_error="$run_error"
            fi
            # The polling interval is also part of live UCI configuration.
            load_exit_config >/dev/null 2>&1 || INTERVAL=5
            sleep "$INTERVAL"
        done
        ;;
    *)
        echo 'Usage: exit-route.sh [run|once|status]' >&2
        exit 2
        ;;
esac
