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

NDPI_REPO="${NDPI_REPO:-https://github.com/vel21ripn/nDPI.git}"
NDPI_BRANCH="${NDPI_BRANCH:-flow_info-4}"
NDPI_COMMIT="${NDPI_COMMIT:-63880be7697149ce954c91346bbd7b8cb8ea34d0}"
NDPI_SRC="${NDPI_SRC:-/usr/local/src/ndpi-netfilter}"
NDPI_SHORT_COMMIT="$(printf '%s' "$NDPI_COMMIT" | cut -c1-7)"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

kernel_config_has() {
    _setting="$1"
    _config="/boot/config-$(uname -r)"
    [ -r "$_config" ] || fail "missing kernel config: $_config"
    grep -Eq "^${_setting}=(y|m)$" "$_config"
}

ndpi_match_works() {
    _test_chain="AWG_NDPI_DEPLOY_TEST"
    /usr/sbin/iptables -N "$_test_chain" 2>/dev/null || true
    /usr/sbin/iptables -F "$_test_chain" >/dev/null 2>&1 || return 1

    if /usr/sbin/iptables -A "$_test_chain" \
        -m ndpi --proto bittorrent -j RETURN >/dev/null 2>&1; then
        _ndpi_test_ok=1
    else
        _ndpi_test_ok=0
    fi

    /usr/sbin/iptables -F "$_test_chain" 2>/dev/null || true
    /usr/sbin/iptables -X "$_test_chain" 2>/dev/null || true
    [ "$_ndpi_test_ok" -eq 1 ]
}

ndpi_netfilter_ready() {
    modinfo xt_ndpi >/dev/null 2>&1 || return 1

    if ! grep -q '^xt_ndpi ' /proc/modules 2>/dev/null; then
        modprobe xt_ndpi >/dev/null 2>&1 || return 1
    fi

    _ndpi_help="$(/usr/sbin/iptables -m ndpi --help 2>&1)" || return 1
    printf '%s\n' "$_ndpi_help" | grep -Fq "$NDPI_SHORT_COMMIT" || return 1
    ndpi_match_works
}

install_ndpi_netfilter() {
    # Use default xt_ndpi settings; the optional BitTorrent/DHT cache is disabled.
    rm -f /etc/modprobe.d/xt_ndpi.conf
    printf '%s\n' xt_ndpi >/etc/modules-load.d/xt_ndpi.conf

    if ndpi_netfilter_ready; then
        echo "OK: xt_ndpi commit=$NDPI_SHORT_COMMIT already installed; skipping build"
        return 0
    fi

    kernel_config_has CONFIG_NF_CONNTRACK \
        || fail "kernel must have CONFIG_NF_CONNTRACK"
    kernel_config_has CONFIG_NF_CONNTRACK_LABELS \
        || fail "kernel must have CONFIG_NF_CONNTRACK_LABELS"
    kernel_config_has CONFIG_NETFILTER_XT_MATCH_CONNLABEL \
        || fail "kernel must have CONFIG_NETFILTER_XT_MATCH_CONNLABEL"

    _kernel_major="$(uname -r | cut -d. -f1)"
    _kernel_minor="$(uname -r | cut -d. -f2 | sed 's/[^0-9].*$//')"
    if [ "${_kernel_major:-0}" -gt 5 ] || {
        [ "${_kernel_major:-0}" -eq 5 ] \
            && [ "${_kernel_minor:-0}" -ge 18 ]
    }; then
        grep -q '^CONFIG_LIVEPATCH=y$' "/boot/config-$(uname -r)" \
            || fail "kernel >= 5.18 needs CONFIG_LIVEPATCH=y for unpatched xt_ndpi"
    fi

    rm -rf "$NDPI_SRC"
    git clone --filter=blob:none --branch "$NDPI_BRANCH" "$NDPI_REPO" "$NDPI_SRC" \
        || fail "failed to clone nDPI"
    (
        cd "$NDPI_SRC" || exit 1
        git checkout --detach "$NDPI_COMMIT" || exit 1
        ./autogen.sh || exit 1
        ./configure || exit 1
        make -C ndpi-netfilter -j"$(nproc)" || exit 1
        make -C ndpi-netfilter modules_install || exit 1
        make -C ndpi-netfilter install || exit 1
    ) || fail "failed to build/install ndpi-netfilter"

    depmod -a || fail "depmod failed after xt_ndpi install"

    # If an older module is already resident, the reboot below will load the new one.
    if ! grep -q '^xt_ndpi ' /proc/modules 2>/dev/null; then
        modprobe xt_ndpi || fail "failed to load xt_ndpi"
    fi

    /usr/sbin/iptables -m ndpi --help >/dev/null 2>&1 \
        || fail "iptables cannot load the ndpi match extension"
    ndpi_match_works \
        || fail "current iptables backend cannot install xt_ndpi rules"

    echo "OK: installed xt_ndpi commit=$NDPI_COMMIT (DHT cache disabled)"
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
    iptables \
    build-essential \
    git \
    gettext \
    flex \
    bison \
    libtool \
    autoconf \
    automake \
    pkg-config \
    libpcap-dev \
    libjson-c-dev \
    libnuma-dev \
    libpcre2-dev \
    libmaxminddb-dev \
    librrd-dev \
    libxtables-dev

install_ndpi_netfilter

add-apt-repository -y ppa:amnezia/ppa

apt-get update
apt-get install -y \
    amneziawg \
    amneziawg-tools \
    amneziawg-dkms

if [ -f /etc/awg-server.sh ]; then
    chmod 0755 /etc/awg-server.sh
fi

systemctl daemon-reload

systemctl enable iperf3
systemctl enable awg-server-network.service
systemctl enable exit-direct-guard.timer

update_deploy_version

reboot
