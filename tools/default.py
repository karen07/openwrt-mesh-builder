#!/usr/bin/env python3
from pathlib import Path

# ============================================================
# PROJECT LAYOUT
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_TEMP_ROOT = Path.cwd()

CONFIG_PATH = Path("config.json")

ROUTERS_ROOT = Path("routers")
SERVER_ROOT = Path("servers")
SERVER_TEMPLATE_NAME = "example"
SERVER_TEMPLATE_DIR = SERVER_ROOT / SERVER_TEMPLATE_NAME

ROUTER_EXAMPLE_DIR = ROUTERS_ROOT / "example"
ROUTER_FILES_DIRNAME = "files"
ROUTER_PACKAGES_DIRNAME = "packages"
PACKAGE_SOURCE_ROOT = Path("packages")
IMAGES_DIR = Path("images")


# ============================================================
# CONFIG KEY NAMES
# ============================================================

CONFIG_KEY_NAME = "name"
CONFIG_KEY_OPENWRT_VERSION = "openwrt_version"
CONFIG_KEY_PACKAGES = "packages"
CONFIG_KEY_DEVICE_PROFILES = "device_profiles"
CONFIG_KEY_MAIN_ROUTER = "main_router"
CONFIG_KEY_ROUTERS = "routers"
CONFIG_KEY_MESH_HUBS = "mesh_hubs"
CONFIG_KEY_EXIT_HUBS = "exit_hubs"
CONFIG_KEY_EXIT_ORDER = "exit_order"
CONFIG_KEY_ACCESS = "access"

CONFIG_KEY_BOARD = "board"
CONFIG_KEY_ARCH = "arch"
CONFIG_KEY_DEVICE_PROFILE = "device_profile"
CONFIG_KEY_SUBNET = "subnet"
CONFIG_KEY_ALLOW_TO_ROUTER = "allow_to_router"
CONFIG_KEY_ALLOW_TO_LAN = "allow_to_lan"
CONFIG_KEY_WIFI_2G = "wifi_2g"
CONFIG_KEY_WIFI_5G = "wifi_5g"
CONFIG_KEY_SSID = "ssid"
CONFIG_KEY_KEY = "key"
CONFIG_KEY_BLOCKED_MACS = "blocked_macs"
CONFIG_KEY_LISTEN_IP = "listen_ip"
CONFIG_KEY_ACCESS_ONLY = "access_only"
CONFIG_KEY_EXIT_IP = "exit_ip"
CONFIG_KEY_PROTOCOL = "protocol"
CONFIG_KEY_POLICY = "policy"
CONFIG_KEY_PORT = "port"
CONFIG_KEY_USERS = "users"
CONFIG_KEY_AWG = "awg"
CONFIG_KEY_SSH_KEY_DIR = "ssh_key_dir"
CONFIG_KEY_SECRET_KEY = "secret_key"  # legacy, rejected by validation
CONFIG_KEY_SECRETS_KEY_PATH = "secrets_key_path"
CONFIG_KEY_MATERIALS_KEY_PATH = "materials_key_path"

# ============================================================
# ROUTER / SERVER NAMING CONVENTIONS
# ============================================================

ROUTER_SSH_PREFIX = "router_"
SERVER_SSH_PREFIX = "server_"
ROUTER_HOSTNAME_PREFIX = "OpenWrt_"

SSH_CONFIG_FILENAME = "config"
SSH_KNOWN_HOSTS_FILENAME = "known_hosts"
ROUTER_KEY_PREFIX = "router"
SERVER_KEY_PREFIX = "server_"
EXIT_HUB_NAME_PREFIX = "Exit"

ROUTER_SECRET_MARKER = "ROUTER_SECRET_V1"  # legacy, rejected
OWMB_PLAIN_SECRET_MARKER = "OWMB_PLAIN_SECRET_V1"
OWMB_ENC_SECRET_MARKER = "OWMB_ENC_SECRET_V1"
OWMB_PLAIN_MATERIAL_MARKER = "OWMB_PLAIN_MATERIAL_V1"
OWMB_ENC_MATERIAL_MARKER = "OWMB_ENC_MATERIAL_V1"
OWMB_SECRETS_KEY_MARKER = "OWMB_SECRETS_KEY_V1"
OWMB_MATERIALS_KEY_MARKER = "OWMB_MATERIALS_KEY_V1"

# ============================================================
# TIMEOUTS / REMOTE OPS
# ============================================================

SSH_TIMEOUT = 1
SCP_TIMEOUT = 15
SSH_COMMAND_TIMEOUT_GRACE_SEC = 10
SCP_COMMAND_TIMEOUT_GRACE_SEC = 20
FILE_MODE_MASK = 0o7777
PRIVATE_KEY_FILE_MODE = 0o600
PRIVATE_SSH_DIR_MODE = 0o700
REMOTE_UPLOAD_DIR = "/tmp"
ASYNC_SYSUPGRADE_DELAY_SEC = 30
ROUTER_VERSION_COMMAND = """grep OPENWRT_RELEASE /etc/os-release | cut -d'"' -f2"""
SERVER_VERSION_COMMAND = """cat /etc/deploy_version"""
REMOTE_ROOT = "/"
REMOTE_DEPLOY_COMMAND = "cd /root && ./deploy.sh"

INSTALL_IMAGE_TYPE_SYSUPGRADE = "sysupgrade"
INSTALL_IMAGE_TYPE_FACTORY = "factory"
INSTALL_IMAGE_TYPES = (
    INSTALL_IMAGE_TYPE_SYSUPGRADE,
    INSTALL_IMAGE_TYPE_FACTORY,
)

# ============================================================
# GENERATED ROUTER FILE LAYOUT
# ============================================================

REL_NETWORK = Path("files/etc/config/network_part")
REL_BABELD = Path("files/etc/config/babeld")
REL_FIREWALL = Path("files/etc/config/firewall_part")
REL_BOOTSTRAP = Path("files/etc/uci-defaults/99-firstboot-custom")
REL_OPENVPN_ROOT = Path("files/etc/openvpn")
REL_OPENVPN_UCI = Path("files/etc/config/openvpn")
REL_WIREGUARD_ROOT = Path("files/etc/wireguard")
REL_DROPBEAR_AUTHORIZED_KEYS = Path("files/etc/dropbear/authorized_keys")
REL_IPSETS_ROOT = Path("files/etc/ipsets")
REL_DIRECT_IPSET = REL_IPSETS_ROOT / "direct.txt"
REL_DIRECT_STATIC_IPSET = REL_IPSETS_ROOT / "direct-static.txt"
REL_RUNTIME_ENV = Path("files/etc/router-autoinstall.env")
RUNTIME_ENV_REMOTE_PATH = "/etc/router-autoinstall.env"
RUNTIME_ENV_FILENAME = "router-autoinstall.env"

REL = {
    "network": REL_NETWORK,
    "babeld": REL_BABELD,
    "firewall": REL_FIREWALL,
    "bootstrap": REL_BOOTSTRAP,
    "openvpn": REL_OPENVPN_ROOT,
    "openvpn_uci": REL_OPENVPN_UCI,
    "wireguard": REL_WIREGUARD_ROOT,
}

# ============================================================
# SYNC RULES
# ============================================================

SYNC_COPY_DIRS = {
    Path("files/etc/crontabs"),
    Path("files/etc/init.d"),
    Path("files/etc/scripts"),
}

SYNC_COPY_FILES = {
    Path("files/etc/config/https-dns-proxy"),
    Path("files/etc/config/watchcat"),
}

SYNC_MERGE_FILES = {
    REL_BOOTSTRAP,
    REL_FIREWALL,
    REL_NETWORK,
}

EXPECTED_MANAGED_ROUTER_DIRS = {
    PACKAGE_SOURCE_ROOT,
}

# ============================================================
# NETWORK / TUNNEL DEFAULTS
# ============================================================


AWG_SERVER_NETWORK_SERVICE_NAME = "awg-server-network.service"
SERVER_ENV_IPSET_NAME = "exit_direct"

IPIP_SERVER_IFACE = "ipip-exit"
NODE_SERVER_IFACE = "awg-node"
# IPIP MTU must be <= AWG/WG MTU - 20.
# With AWG/WG MTU 1420, IPIP MTU 1400 is the maximum.
IPIP_DEFAULT_MTU: int | None = 1400

# Generated compact exit service marker prefixes.
# 10.254.0.0/24 is split into stable hash-selected /31 prefixes by exit name.
EXIT_ANNOUNCE_SUPERNET4 = "10.254.0.0/24"
EXIT_ANNOUNCE_PREFIXLEN = 31

# Generated stable node/control prefixes for exit SSH/healthcheck addresses.
# The first address of a hash-selected /31 in this supernet is used.
EXIT_NODE_SUPERNET4 = "10.254.1.0/24"
EXIT_NODE_PREFIXLEN = 31

TUNNEL_MTU: int | None = None
KEEPALIVE = 1
ACCESS_HOST_START = 2
ACCESS_SERVER_HOST = 1
ACCESS_SUBNET_CIDR = 24
CLIENT_TUNNEL_CIDR = 32

IPV4_OCTET_COUNT = 4
IPV4_OCTET_MIN = 0
IPV4_OCTET_MAX = 255
PORT_MIN = 1
PORT_MAX = 65535
P2P_LINK_PREFIXLEN = 31
P2P_LINK_HOST_STRIDE = 2
INFRA_LINK_POOL = "10.255.0.0/16"
IPV4_LINK_LOCAL_PREFIXLEN = 64
STABLE_HASH_U32_DIGEST_SIZE = 4
STABLE_SEED_U64_DIGEST_SIZE = 8
SHELL_SECRET_WRAP_COL = 60
ANON_LINK_ALIAS_HEX_LEN = 8
UNMANAGED_REPORT_HASH_LEN = 7

DEFAULT_ALLOWED_IPS = ["0.0.0.0/0", "::/0"]
DEFAULT_ALLOWED_IPS_TEXT = ", ".join(DEFAULT_ALLOWED_IPS)

INFRA_AWG_PORT_RANGE = "20000-32767"

PROTOCOL_WIREGUARD = "wireguard"
PROTOCOL_OPENVPN = "openvpn"
PROTOCOL_AMNEZIAWG = "amneziawg"

ACCESS_POLICY_TRUSTED = "trusted"
ACCESS_POLICY_TRANSIT = "transit"

# ============================================================
# FIREWALL / UCI CONVENTIONS
# ============================================================

FIREWALL_MARKER = "# Unique part up to this line"
TRANSIT_ACCESS_DNS_RULE_NAME = "Allow-DNS-TransitAccess"

ZONE_MESH = "Mesh"
ZONE_EXIT = "Exit"
ZONE_EXIT_IPIP = "ExitIPIP"
ZONE_TRUSTED_ACCESS = "TrustedAccess"
ZONE_TRANSIT_ACCESS = "TransitAccess"
MANAGED_FIREWALL_ZONES = (
    ZONE_MESH,
    ZONE_EXIT,
    ZONE_TRUSTED_ACCESS,
    ZONE_TRANSIT_ACCESS,
)

FIREWALL_ZONE_LAN = "lan"
FIREWALL_ZONE_WAN = "wan"
FIREWALL_RULE_ALLOW_MESH = "Allow-Mesh"
FIREWALL_TARGET_ALL = "all"
FIREWALL_TARGET_ACCEPT = "ACCEPT"
FIREWALL_TARGET_REJECT = "REJECT"

DNS_PORT = 53
TRANSPORT_TCP = "tcp"
TRANSPORT_UDP = "udp"
DNS_PROTOCOLS = [TRANSPORT_TCP, TRANSPORT_UDP]

# ============================================================
# OPENVPN DEFAULTS
# ============================================================

DEFAULT_CA_CN = "Root CA"
DEFAULT_CERT_DAYS = 3650

OPENVPN_SERVER_CN = "server"
OPENVPN_SERVER_PROTO = "tcp-server"
OPENVPN_CLIENT_PROTO = "tcp-client"
OPENVPN_DEV_TYPE = "tun"
OPENVPN_TOPOLOGY = "subnet"
OPENVPN_DATA_CIPHERS = "CHACHA20-POLY1305"
OPENVPN_KEEPALIVE = "10 120"
OPENVPN_USER = "nobody"
OPENVPN_GROUP = "nogroup"
OPENVPN_VERB = 0

# ============================================================
# BABELD DEFAULTS
# ============================================================

BABELD_LOG_FILE = "/dev/null"
BABELD_UBUS_BINDINGS = "true"
BABELD_TUNNEL_TYPE = "tunnel"
BABELD_SPLIT_HORIZON = "true"
BABELD_HELLO_INTERVAL = 2
BABELD_UPDATE_INTERVAL = 10
BABELD_LAN_IFACE = "br-lan"

SERVER_BABELD_CONF_PREFIX = "/etc/babel"
SERVER_BABELD_CONF_SUFFIX = ".conf"

# ============================================================
# WIFI BOOTSTRAP DEFAULTS
# ============================================================

WIFI_RADIO_BY_KEY = {
    "wifi_2g": ("radio0", "default_radio0"),
    "wifi_5g": ("radio1", "default_radio1"),
}

WIFI_COUNTRY = "RU"
WIFI_ENCRYPTION = "psk2"
WIFI_CELL_DENSITY = "0"

# ============================================================
# OPENWRT / AWG PACKAGE BUILD DEFAULTS
# ============================================================

MIN_OPENWRT_MAJOR = 25
MIN_OPENWRT_MINOR = 12
MIN_OPENWRT_VERSION = (MIN_OPENWRT_MAJOR, MIN_OPENWRT_MINOR)
MIN_OPENWRT_VERSION_TEXT = f"{MIN_OPENWRT_MAJOR}.{MIN_OPENWRT_MINOR}"

OPENWRT_RELEASE_BASE_URL = "https://downloads.openwrt.org/releases"
AWG_RELEASE_BASE_URL = "https://github.com/karen07/amneziawg-openwrt/releases/download"

AWG_PACKAGE_NAMES = [
    "kmod-amneziawg",
    "amneziawg-tools",
    "luci-proto-amneziawg",
]

# OpenWrt image packages required by generated router configs and
# router example files. User-facing config.packages is for extra packages.
ROUTER_REQUIRED_PACKAGES = [
    "babeld",
    "curl",
    "iperf3",
    "jq-full",
    "luci-app-https-dns-proxy",
    "luci-app-watchcat",
    "luci-proto-amneziawg",
    "luci-proto-ipip",
    "luci",
]

ROUTER_REQUIRED_ACCESS_PACKAGES = {
    PROTOCOL_WIREGUARD: ["luci-proto-wireguard"],
    PROTOCOL_OPENVPN: ["openvpn-openssl"],
    PROTOCOL_AMNEZIAWG: [],
}
PACKAGE_EXTENSION = "apk"
PACKAGE_REPO_INDEX_FILES = (
    "packages.adb",
    "Packages",
    "Packages.gz",
    "Packages.manifest",
)

GITHUB_RAW_BASE_URL = "https://raw.githubusercontent.com"
URL_IPVERSE_RIR = f"{GITHUB_RAW_BASE_URL}/ipverse/country-ip-blocks/master"
URL_IPVERSE_ASN = f"{GITHUB_RAW_BASE_URL}/ipverse/as-ip-blocks/master"
LOCAL_DIRECT_IPSETS = [
    # Bootstrap / local / private / provider-local
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    # IETF special-use / docs / benchmarks / deprecated / reserved
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "240.0.0.0/4",
    # Multicast
    "224.0.0.0/4",
]

EXIT_DIRECT_STATIC_IPSETS = []
EXIT_DIRECT_COUNTRIES = ["ru", "cn", "by"]
EXIT_DIRECT_ASNS = [
    32590,
]

# ============================================================
# GENERATED RUNTIME ENV DEFAULTS
# ============================================================

CHECK_DOH_DOMAIN = "google.com"
CHECK_DOH_INTERVAL = 5
CHECK_DOH_RESOLV = "/tmp/resolv.conf.d/resolv.conf.auto"
CHECK_DOH_RESOLV_WAIT_MAX = 300
CHECK_DOH_PROVIDER_DOMAINS = ["ru", "xn--p1ai"]

EXIT_ROUTE_TABLE = 200
EXIT_ROUTE_INTERVAL = 5

RUNTIME_IPSETS_DIR = "/etc/ipsets"
RUNTIME_DIRECT_STATIC_NAME = "direct-static.txt"
RUNTIME_DIRECT_OUT_NAME = "direct.txt"
UPDATE_IPSETS_CURL_CONNECT_TIMEOUT = 10
UPDATE_IPSETS_CURL_MAX_TIME = 60
UPDATE_IPSETS_CURL_RETRY = 3

# ============================================================
# AWG PARAMETER DEFAULTS
# ============================================================

# AmneziaWG runtime parameter ranges accepted in explicit config.
AWG_JC_MIN = 1
AWG_JC_MAX = 10
AWG_JUNK_SIZE_MIN = 64
AWG_JUNK_SIZE_MAX = 1024
AWG_S1_MIN = 1
AWG_S1_MAX = 64
AWG_S2_MIN = 1
AWG_S2_MAX = 64
AWG_S3_MIN = 1
AWG_S3_MAX = 64
AWG_S4_MIN = 1
AWG_S4_MAX = 16

# Deterministic infra auto-generation ranges.  They intentionally mirror the
# accepted AmneziaWG ranges except S4, which is capped more conservatively
# because it is added to data packets and can affect path MTU.
AWG_INFRA_AUTO_JC_MIN = AWG_JC_MIN
AWG_INFRA_AUTO_JC_MAX = AWG_JC_MAX
AWG_INFRA_AUTO_JUNK_SIZE_MIN = AWG_JUNK_SIZE_MIN
AWG_INFRA_AUTO_JUNK_SIZE_MAX = AWG_JUNK_SIZE_MAX
AWG_INFRA_AUTO_S1_MIN = AWG_S1_MIN
AWG_INFRA_AUTO_S1_MAX = AWG_S1_MAX
AWG_INFRA_AUTO_S2_MIN = AWG_S2_MIN
AWG_INFRA_AUTO_S2_MAX = AWG_S2_MAX
AWG_INFRA_AUTO_S3_MIN = AWG_S3_MIN
AWG_INFRA_AUTO_S3_MAX = AWG_S3_MAX
AWG_INFRA_AUTO_S4_MIN = AWG_S4_MIN
AWG_INFRA_AUTO_S4_MAX = AWG_S4_MAX

# AWG H range generator defaults.
AWG_H_COUNT = 4
AWG_H_SPAN_MIN = 65_536
AWG_H_SPAN_MAX = 262_144
AWG_H_MIN = 0
AWG_H_MAX = 4_294_967_295
AWG_H_GAP = 0

# Infra links derive J/S/H parameters from the stable per-link hash.
# I1-I5 are static CPS templates used for all generated infra links.
AWG_INFRA_I1 = "<r 128>"
AWG_INFRA_I2 = ""
AWG_INFRA_I3 = ""
AWG_INFRA_I4 = ""
AWG_INFRA_I5 = ""

# ============================================================
# TOPOLOGY RENDER DEFAULTS
# ============================================================

TOPOLOGY_CACHE_TTL_SEC = 300
TOPOLOGY_NODE_R = 38
TOPOLOGY_DIR = "topology"
TOPOLOGY_2D_OUT = "topology/topology_2d.svg"
TOPOLOGY_3D_OUT = "topology/topology_3d.html"
TOPOLOGY_OUT = TOPOLOGY_2D_OUT
TOPOLOGY_TITLE = "Mesh topology"
TOPOLOGY_HTTP_PORT = 8080

IPERF_TIME_SEC = 1
IPERF_BITRATE = ""

SPEED_MIN_MBPS = 5.0
SPEED_MAX_MBPS = 500.0

LINK_STATUS_UP = "up"
LINK_STATUS_DOWN = "down"
