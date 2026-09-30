#!/bin/sh

if [ -r /etc/router-autoinstall.env ]; then
    # Generated file, loaded once at startup. Restart to apply changes.
    # shellcheck disable=SC1091
    . /etc/router-autoinstall.env
fi

HOSTS="${PING_REBOOT_HOSTS:-}"
ARM_SUCCESSES="${PING_REBOOT_ARM_SUCCESSES:-5}"
UNARMED_REBOOT="${PING_REBOOT_UNARMED_REBOOT:-3600}"
INTERVAL="${PING_REBOOT_INTERVAL:-10}"
MAX_FAILURES="${PING_REBOOT_MAX_FAILURES:-5}"
TIMEOUT="${PING_REBOOT_TIMEOUT:-2}"

if [ -z "$HOSTS" ]; then
    echo "PING_REBOOT_HOSTS is empty in /etc/router-autoinstall.env"
    exit 1
fi

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
