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

AWG_KERNEL_REPO="${AWG_KERNEL_REPO:-amnezia-vpn/amneziawg-linux-kernel-module}"
AWG_TOOLS_REPO="${AWG_TOOLS_REPO:-amnezia-vpn/amneziawg-tools}"
AWG_KERNEL_SRC="${AWG_KERNEL_SRC:-/usr/local/src/amneziawg-linux-kernel-module}"
AWG_TOOLS_SRC="${AWG_TOOLS_SRC:-/usr/local/src/amneziawg-tools}"

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

remove_amnezia_ppa() {
    _removed=0

    for _source in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
        [ -f "$_source" ] || continue
        if grep -Eiq 'ppa\.launchpad(content)?\.net/amnezia/ppa' "$_source"; then
            echo "Removing Amnezia PPA source: $_source"
            rm -f "$_source"
            _removed=1
        fi
    done

    if [ -f /etc/apt/sources.list ] \
        && grep -Eiq 'ppa\.launchpad(content)?\.net/amnezia/ppa' /etc/apt/sources.list; then
        sed -i \
            -e '\#ppa\.launchpadcontent\.net/amnezia/ppa#d' \
            -e '\#ppa\.launchpad\.net/amnezia/ppa#d' \
            /etc/apt/sources.list
        _removed=1
    fi

    if [ "$_removed" -eq 1 ]; then
        echo "OK: removed Amnezia PPA; AmneziaWG will be built from release sources"
    fi
}

purge_packaged_amneziawg() {
    _packages=""
    for _package in amneziawg amneziawg-tools amneziawg-dkms; do
        if dpkg-query -W -f='${db:Status-Abbrev}' "$_package" 2>/dev/null \
            | grep -q '^ii'; then
            _packages="$_packages $_package"
        fi
    done

    [ -n "$_packages" ] || return 0

    echo "Removing packaged AmneziaWG before source/DKMS installation:$_packages"
    # Package names above are fixed constants; intentional word splitting is required.
    # shellcheck disable=SC2086
    apt-get purge -y $_packages \
        || fail "failed to remove packaged AmneziaWG"
}

awg_valid_release_tag() {
    printf '%s\n' "$1" \
        | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]{8}([.-][0-9]+)?$'
}

awg_release_family() {
    printf '%s\n' "$1" \
        | sed -n 's/^v\([0-9][0-9]*\)\.\([0-9][0-9]*\)\..*$/\1.\2/p'
}

latest_awg_release_tag() {
    _repo="$1"

    # Amnezia does not consistently create GitHub Release objects for every
    # published AWG version.  The versioned vX.Y.YYYYMMDD tags are the stable
    # release markers used by both upstream repositories, so resolve those
    # directly and never build a moving branch such as master.
    git ls-remote --refs --tags \
        "https://github.com/${_repo}.git" 'v*' 2>/dev/null \
        | awk -F/ '{print $3}' \
        | grep -E '^v[0-9]+\.[0-9]+\.[0-9]{8}([.-][0-9]+)?$' \
        | sort -V \
        | tail -n 1
}

installed_awg_tools_version() {
    command -v awg >/dev/null 2>&1 || return 1
    awg --version 2>/dev/null \
        | sed -n 's/^amneziawg-tools v\([^ ]*\).*$/\1/p'
}

awg_dkms_status() {
    _version="$1"
    dkms status \
        -m amneziawg \
        -v "$_version" \
        -k "$(uname -r)" 2>/dev/null || true
}

awg_dkms_registered() {
    _version="$1"
    dkms status -m amneziawg -v "$_version" 2>/dev/null \
        | grep -q "^amneziawg/${_version}"
}

awg_kernel_installed() {
    _version="$1"
    awg_dkms_status "$_version" | grep -q ': installed'
}

awg_kernel_release_ready() {
    _version="$1"
    awg_kernel_installed "$_version" || return 1

    _module_path="$(
        modinfo -k "$(uname -r)" -n amneziawg 2>/dev/null || true
    )"

    case "$_module_path" in
        */updates/dkms/amneziawg.ko | */updates/dkms/amneziawg.ko.*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

awg_tools_release_ready() {
    _version="$1"
    [ "$(installed_awg_tools_version || true)" = "$_version" ] \
        || return 1
    command -v awg-quick >/dev/null 2>&1
}

prepare_awg_dkms_source() {
    _tag="$1"
    _version="${_tag#v}"
    _dkms_source="/usr/src/amneziawg-${_version}"

    if [ -f "$_dkms_source/dkms.conf" ] \
        && grep -Fqx "PACKAGE_VERSION=\"${_version}\"" "$_dkms_source/dkms.conf"; then
        return 0
    fi

    rm -rf "$AWG_KERNEL_SRC"
    git clone \
        --depth 1 \
        --branch "$_tag" \
        "https://github.com/${AWG_KERNEL_REPO}.git" \
        "$AWG_KERNEL_SRC" \
        || fail "failed to clone AmneziaWG kernel $_tag"

    _checked_out_tag="$(
        git -C "$AWG_KERNEL_SRC" describe --tags --exact-match 2>/dev/null || true
    )"
    [ "$_checked_out_tag" = "$_tag" ] \
        || fail "AmneziaWG kernel checkout is not exact tag $_tag"

    grep -q '^WIREGUARD_VERSION = ' "$AWG_KERNEL_SRC/src/Makefile" \
        || fail "cannot locate WIREGUARD_VERSION in AmneziaWG kernel Makefile"
    grep -q '^PACKAGE_VERSION=' "$AWG_KERNEL_SRC/src/dkms.conf" \
        || fail "cannot locate PACKAGE_VERSION in AmneziaWG dkms.conf"

    # Upstream release packaging stamps the real release version into both
    # files before registering the source tree with DKMS.  Do the same here.
    sed -i \
        "s/^WIREGUARD_VERSION = .*/WIREGUARD_VERSION = ${_version}/" \
        "$AWG_KERNEL_SRC/src/Makefile"
    sed -i \
        "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\"${_version}\"/" \
        "$AWG_KERNEL_SRC/src/dkms.conf"

    grep -Fqx "WIREGUARD_VERSION = ${_version}" "$AWG_KERNEL_SRC/src/Makefile" \
        || fail "failed to stamp AmneziaWG kernel version $_version"
    grep -Fqx "PACKAGE_VERSION=\"${_version}\"" "$AWG_KERNEL_SRC/src/dkms.conf" \
        || fail "failed to stamp AmneziaWG DKMS version $_version"

    rm -rf "$_dkms_source"
    make \
        -C "$AWG_KERNEL_SRC/src" \
        DKMSDIR="$_dkms_source" \
        dkms-install \
        || fail "failed to install AmneziaWG $_tag sources into $_dkms_source"
}

install_awg_kernel_release() {
    _tag="$1"
    _version="${_tag#v}"
    _kernel="$(uname -r)"

    if awg_kernel_release_ready "$_version"; then
        echo "OK: AmneziaWG kernel $_tag already installed for $_kernel; skipping build"
        return 0
    fi

    echo "Installing AmneziaWG kernel release $_tag for $_kernel..."
    prepare_awg_dkms_source "$_tag"

    if ! awg_dkms_registered "$_version"; then
        dkms add -m amneziawg -v "$_version" \
            || fail "dkms add failed for AmneziaWG $_tag"
    fi

    if ! awg_dkms_status "$_version" | grep -Eq ': (built|installed)'; then
        dkms build -m amneziawg -v "$_version" -k "$_kernel" \
            || fail "dkms build failed for AmneziaWG $_tag on $_kernel"
    fi

    dkms install \
        -m amneziawg \
        -v "$_version" \
        -k "$_kernel" \
        --force \
        || fail "dkms install failed for AmneziaWG $_tag on $_kernel"

    depmod -a || fail "depmod failed after AmneziaWG DKMS install"

    awg_kernel_release_ready "$_version" \
        || fail "AmneziaWG $_tag is not selected from DKMS for $_kernel"

    if grep -q '^amneziawg ' /proc/modules 2>/dev/null; then
        _loaded_version="$(
            cat /sys/module/amneziawg/version 2>/dev/null || true
        )"
        echo "NOTICE: AmneziaWG $_tag installed; loaded module reports" \
            "${_loaded_version:-unknown}; reboot activates the new build"
    else
        modprobe amneziawg \
            || fail "failed to load AmneziaWG kernel module $_tag"
        [ -d /sys/module/amneziawg ] \
            || fail "AmneziaWG module did not load after modprobe"
    fi

    echo "OK: installed AmneziaWG kernel $_tag"
}

install_awg_tools_release() {
    _tag="$1"
    _version="${_tag#v}"
    _installed_version="$(installed_awg_tools_version || true)"

    if awg_tools_release_ready "$_version"; then
        echo "OK: amneziawg-tools $_tag already installed; skipping build"
        return 0
    fi

    echo "Installing amneziawg-tools release $_tag (current=${_installed_version:-none})..."

    rm -rf "$AWG_TOOLS_SRC"
    git clone \
        --depth 1 \
        --branch "$_tag" \
        "https://github.com/${AWG_TOOLS_REPO}.git" \
        "$AWG_TOOLS_SRC" \
        || fail "failed to clone amneziawg-tools $_tag"

    _checked_out_tag="$(
        git -C "$AWG_TOOLS_SRC" describe --tags --exact-match 2>/dev/null || true
    )"
    [ "$_checked_out_tag" = "$_tag" ] \
        || fail "amneziawg-tools checkout is not exact tag $_tag"

    make -C "$AWG_TOOLS_SRC/src" -j"$(nproc)" \
        || fail "failed to build amneziawg-tools $_tag"

    make \
        -C "$AWG_TOOLS_SRC/src" \
        BINDIR=/usr/bin \
        MANDIR=/usr/share/man \
        RUNSTATEDIR=/run \
        WITH_BASHCOMPLETION=yes \
        WITH_WGQUICK=yes \
        WITH_SYSTEMDUNITS=yes \
        install \
        || fail "failed to install amneziawg-tools $_tag"

    _installed_version="$(installed_awg_tools_version || true)"
    [ "$_installed_version" = "$_version" ] \
        || fail "installed amneziawg-tools version=$_installed_version, expected=$_version"

    command -v awg-quick >/dev/null 2>&1 \
        || fail "awg-quick was not installed"

    echo "OK: installed amneziawg-tools $_tag"
}

install_amneziawg() {
    echo "Detecting latest AmneziaWG releases..."

    _tools_tag="$(latest_awg_release_tag "$AWG_TOOLS_REPO" || true)"
    [ -n "$_tools_tag" ] \
        || fail "failed to determine latest amneziawg-tools release tag"

    _kernel_tag="$(latest_awg_release_tag "$AWG_KERNEL_REPO" || true)"
    [ -n "$_kernel_tag" ] \
        || fail "failed to determine latest AmneziaWG kernel release tag"

    awg_valid_release_tag "$_tools_tag" \
        || fail "invalid amneziawg-tools release tag: $_tools_tag"
    awg_valid_release_tag "$_kernel_tag" \
        || fail "invalid AmneziaWG kernel release tag: $_kernel_tag"

    _tools_family="$(awg_release_family "$_tools_tag")"
    _kernel_family="$(awg_release_family "$_kernel_tag")"
    [ -n "$_tools_family" ] \
        || fail "cannot parse amneziawg-tools release: $_tools_tag"
    [ -n "$_kernel_family" ] \
        || fail "cannot parse AmneziaWG kernel release: $_kernel_tag"

    echo "AmneziaWG releases:"
    echo "  kernel: $_kernel_tag"
    echo "  tools:  $_tools_tag"

    if [ "$_kernel_family" != "$_tools_family" ]; then
        fail "AmneziaWG release family mismatch: kernel=$_kernel_tag tools=$_tools_tag"
    fi

    echo "OK: compatible AmneziaWG release family $_kernel_family"

    # These are intentionally independent.  A repeated deploy upgrades only
    # the component whose upstream release changed.
    install_awg_kernel_release "$_kernel_tag"
    install_awg_tools_release "$_tools_tag"
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

# A server deployed by an older version may still have the Amnezia PPA.
# Remove it before apt refresh so future deploys no longer depend on Launchpad.
remove_amnezia_ppa

apt-get update

apt-get install -y \
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
    dkms \
    bc \
    libelf-dev \
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

# One-time migration from the old PPA packages.  On subsequent source-based
# deploys this is a no-op.
purge_packaged_amneziawg

install_ndpi_netfilter
install_amneziawg

if [ -f /etc/awg-server.sh ]; then
    chmod 0755 /etc/awg-server.sh
fi

systemctl daemon-reload

systemctl enable iperf3
systemctl enable awg-server-network.service
systemctl enable exit-direct-guard.timer

update_deploy_version

reboot
