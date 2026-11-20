#!/bin/sh

# shellcheck disable=SC1091
. /lib/functions.sh
TAG=ping-reboot
log_notice() { logger -t "$TAG" -p daemon.notice "$*" 2>/dev/null || :; }
log_warn() { logger -t "$TAG" -p daemon.warning "$*" 2>/dev/null || :; }
log_err() { logger -t "$TAG" -p daemon.err "$*" 2>/dev/null || :; }
log_crit() { logger -t "$TAG" -p daemon.crit "$*" 2>/dev/null || :; }
log_debug() { [ "${LOG_DEBUG:-0}" = 1 ] && logger -t "$TAG" -p daemon.debug "$*" || :; }

config_load ping_reboot
ARM_SUCCESSES='5'
UNARMED_REBOOT='3600'
INTERVAL='10'
MAX_FAILURES='5'
TIMEOUT='2'
HOSTS=''
add_host() { HOSTS="${HOSTS:+$HOSTS }$1"; }
config_list_foreach main host add_host
config_get ARM_SUCCESSES main arm_successes 5
config_get UNARMED_REBOOT main unarmed_reboot 3600
config_get INTERVAL main interval 10
config_get MAX_FAILURES main max_failures 5
config_get TIMEOUT main timeout 2
[ -n "$HOSTS" ] || {
    log_err 'no ping hosts configured'
    echo 'ping_reboot: no hosts configured' >&2
    exit 1
}

any_host_reachable() {
    host=""

    for host in $HOSTS; do
        if ping -c 1 -W "$TIMEOUT" "$host" >/dev/null 2>&1; then
            return 0
        fi
    done

    return 1
}

apply_once() {
    if any_host_reachable; then
        return 0
    fi

    return 1
}

monotonic_seconds() {
    cut -d. -f1 /proc/uptime
}

case "${1:-run}" in
    once)
        if apply_once; then
            echo "connectivity OK"
            exit 0
        fi

        echo "all ping hosts unreachable"
        exit 1
        ;;

    run)
        armed=0
        successes=0
        failures=0
        unarmed_started="$(monotonic_seconds)"
        log_notice "started: hosts=[$HOSTS] interval=${INTERVAL}s timeout=${TIMEOUT}s" \
            "arm_successes=$ARM_SUCCESSES max_failures=$MAX_FAILURES" \
            "unarmed_reboot=${UNARMED_REBOOT}s"
        trap 'log_notice "service stopped"; exit 0' TERM INT

        while true; do
            if apply_once; then
                if [ "$armed" -eq 0 ]; then
                    successes=$((successes + 1))
                    log_debug "connectivity warmup: ${successes}/${ARM_SUCCESSES}"
                    if [ "$successes" -ge "$ARM_SUCCESSES" ]; then
                        armed=1
                        failures=0
                        log_notice "connectivity stable; watchdog armed"
                    fi
                else
                    if [ "$failures" -gt 0 ]; then
                        log_notice "connectivity restored after ${failures} failed check(s)"
                    fi
                    failures=0
                fi
            else
                if [ "$armed" -eq 0 ]; then
                    if [ "$successes" -gt 0 ]; then
                        log_warn "connectivity warmup interrupted:" \
                            "${successes}/${ARM_SUCCESSES}; counter reset"
                    else
                        log_warn "all ping hosts unreachable; watchdog not armed"
                    fi
                    successes=0
                else
                    failures=$((failures + 1))
                    if [ "$failures" -eq 1 ]; then
                        log_warn "connectivity lost: failures=${failures}/${MAX_FAILURES}," \
                            "hosts=[$HOSTS]"
                    else
                        log_debug "connectivity still lost: failures=${failures}/${MAX_FAILURES}"
                    fi
                    if [ "$failures" -ge "$MAX_FAILURES" ]; then
                        log_crit "reboot requested: all ping hosts unreachable," \
                            "failures=${failures}/${MAX_FAILURES}"
                        sync
                        reboot || log_err "reboot command failed after connectivity loss"
                        exit 0
                    fi
                fi
            fi

            if [ "$armed" -eq 0 ] && [ "$UNARMED_REBOOT" -gt 0 ]; then
                now="$(monotonic_seconds)"
                unarmed_elapsed=$((now - unarmed_started))
                if [ "$unarmed_elapsed" -ge "$UNARMED_REBOOT" ]; then
                    log_crit "reboot requested: watchdog unarmed for ${unarmed_elapsed}s" \
                        "(limit=${UNARMED_REBOOT}s)"
                    sync
                    reboot || log_err "reboot command failed after unarmed timeout"
                    exit 0
                fi
            fi
            sleep "$INTERVAL"
        done
        ;;
    *)
        echo "Usage: $0 [run|once]" >&2
        exit 2
        ;;
esac
