#!/bin/sh

update_deploy_version() {
    tmp_version=/root/deploy_version
    out_version=/etc/deploy_version

    [ -s "$tmp_version" ] || return 0

    deploy_version="$(tr -d '\r\n' <"$tmp_version")"
    [ -n "$deploy_version" ] || return 1

    case "$deploy_version" in
        [0-9a-f][0-9a-f]*" "[0-9][0-9][0-9][0-9]-*) ;;
        unknown" "[0-9][0-9][0-9][0-9]-*) ;;
        *) return 1 ;;
    esac

    os_version="Linux"
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        os_version="${PRETTY_NAME:-Linux}"
    fi

    printf '%s %s\n' "$os_version" "$deploy_version" >"$out_version"
    rm -f "$tmp_version"
}

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

apt-get update

apt-get install -y \
    software-properties-common \
    python3-launchpadlib \
    gnupg2 \
    ca-certificates \
    curl \
    "linux-headers-$(uname -r)" \
    vim \
    htop \
    babeld \
    ipset \
    iperf3 \
    jq \
    iptables

add-apt-repository -y ppa:amnezia/ppa

apt-get update
apt-get install -y amneziawg

if [ -f /etc/awg-server.sh ]; then
    chmod 0755 /etc/awg-server.sh
fi

systemctl daemon-reload

systemctl enable iperf3
systemctl enable awg-server-network.service
systemctl enable exit-direct-guard.timer

update_deploy_version

reboot
