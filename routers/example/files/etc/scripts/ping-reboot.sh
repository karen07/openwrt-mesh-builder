#!/bin/sh

# shellcheck disable=SC1091
. /lib/functions.sh
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

        echo "started: hosts=[$HOSTS] interval=${INTERVAL}s"
        echo "arm_successes=$ARM_SUCCESSES unarmed_reboot=${UNARMED_REBOOT}s"
        echo "max_failures=$MAX_FAILURES timeout=${TIMEOUT}s"

        while true; do
            if apply_once; then
                if [ "$armed" -eq 0 ]; then
                    successes=$((successes + 1))
                    echo "connectivity warmup: ${successes}/${ARM_SUCCESSES} successful check(s)"

                    if [ "$successes" -ge "$ARM_SUCCESSES" ]; then
                        armed=1
                        failures=0
                        echo "connectivity stable; reboot watchdog armed"
                    fi
                else
                    if [ "$failures" -gt 0 ]; then
                        echo "connectivity restored after ${failures} failed check(s)"
                    fi
                    failures=0
                fi
            else
                if [ "$armed" -eq 0 ]; then
                    if [ "$successes" -gt 0 ]; then
                        echo "connectivity warmup interrupted; successful check counter reset"
                    fi
                    successes=0
                    echo "connectivity not ready; reboot watchdog not armed"
                else
                    failures=$((failures + 1))
                    echo "all ping hosts unreachable: ${failures}/${MAX_FAILURES}"

                    if [ "$failures" -ge "$MAX_FAILURES" ]; then
                        echo "connectivity lost; rebooting router"
                        sync
                        reboot
                        exit 0
                    fi
                fi
            fi

            if [ "$armed" -eq 0 ] && [ "$UNARMED_REBOOT" -gt 0 ]; then
                now="$(monotonic_seconds)"
                unarmed_elapsed=$((now - unarmed_started))

                if [ "$unarmed_elapsed" -ge "$UNARMED_REBOOT" ]; then
                    echo "watchdog remained unarmed for ${unarmed_elapsed}s; hard recovery reboot"
                    sync
                    reboot
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
