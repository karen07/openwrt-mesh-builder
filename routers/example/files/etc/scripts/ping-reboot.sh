#!/bin/sh

if [ -r /etc/router-autoinstall.env ]; then
    # Generated file, loaded once at startup. Restart to apply changes.
    # shellcheck disable=SC1091
    . /etc/router-autoinstall.env
fi

HOSTS="${PING_REBOOT_HOSTS:-}"
BOOT_GRACE="${PING_REBOOT_BOOT_GRACE:-300}"
INTERVAL="${PING_REBOOT_INTERVAL:-10}"
MAX_FAILURES="${PING_REBOOT_MAX_FAILURES:-3}"
TIMEOUT="${PING_REBOOT_TIMEOUT:-2}"

if [ -z "$HOSTS" ]; then
    echo "PING_REBOOT_HOSTS is empty in /etc/router-autoinstall.env"
    exit 1
fi

router_uptime_seconds() {
    awk '{ print int($1) }' /proc/uptime 2>/dev/null
}

wait_for_boot_grace() {
    uptime_s="$(router_uptime_seconds)"

    case "$uptime_s" in
        '' | *[!0-9]*)
            echo "cannot read router uptime; waiting full ${BOOT_GRACE}s startup grace"
            sleep "$BOOT_GRACE"
            return 0
            ;;
        *)
            ;;
    esac

    if [ "$uptime_s" -lt "$BOOT_GRACE" ]; then
        remaining=$((BOOT_GRACE - uptime_s))
        echo "startup grace: router uptime=${uptime_s}s, waiting ${remaining}s"
        sleep "$remaining"
    fi
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
        wait_for_boot_grace
        failures=0

        echo "started: hosts=[$HOSTS] interval=${INTERVAL}s"
        echo "max_failures=$MAX_FAILURES timeout=${TIMEOUT}s"

        while true; do
            sleep "$INTERVAL"

            if apply_once; then
                if [ "$failures" -gt 0 ]; then
                    echo "connectivity restored after ${failures} failed check(s)"
                fi
                failures=0
                continue
            fi

            failures=$((failures + 1))
            echo "all ping hosts unreachable: ${failures}/${MAX_FAILURES}"

            if [ "$failures" -ge "$MAX_FAILURES" ]; then
                echo "connectivity lost; rebooting router"
                sync
                reboot
                exit 0
            fi
        done
        ;;

    *)
        echo "Usage: $0 [run|once]" >&2
        exit 2
        ;;
esac
