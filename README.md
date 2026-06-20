# OpenWrt Spine-Leaf Mesh Builder

![Topology](./topology.svg)

OpenWrt Spine-Leaf Mesh Builder строит routed mesh/fabric из OpenWrt-роутеров и Linux exit-серверов. Топология описывается в `config.json`, а генератор выводит из неё OpenWrt overlay-файлы, server configs, access-клиентов, SSH aliases, firewall rules, Babel routing, IPIP exit data-plane и OpenWrt ImageBuilder-образы.

Проект рассчитан на OpenWrt `25.12+` и apk-only/AWG2 builds.

## Что получается

- **Spine/router с публичным endpoint** принимает infra-туннели от leaf-роутеров, других spine и exit-серверов.
- **Leaf/router за NAT** сам поднимает outbound infra-туннели к публичным spine и участвует в routed overlay.
- **Exit-сервер** даёт управляемый egress в интернет. Public exit принимает tunnel-связи напрямую, reverse/internal exit сам подключается к spine.
- **Access-группы** дают пользовательский вход в сеть через WireGuard, AmneziaWG или OpenVPN.
- **Babel** строит динамическую маршрутизацию поверх tunnel-интерфейсов.
- **IPIP data-plane** переносит пользовательский трафик до выбранного exit, а путь до IPIP endpoint выбирается overlay routing-ом.
- **Firewall model** остаётся явной: LAN, Mesh, Exit, ExitIPIP, TrustedAccess и TransitAccess разделяются зонами и правилами.

Сеть получается не как один VPN-туннель до одного сервера, а как routed fabric: LAN одного роутера может попасть в LAN другого, access-клиент может зайти через один публичный endpoint и дойти до нужного remote segment, а egress может переключаться между exit-ами по доступности.

## Слои сети

```text
WAN underlay        провайдерские сети, NAT, VPS, публичные и серые IP
encrypted overlay   p2p AWG/WG-линки между router/spine/exit
routing plane       Babel поверх tunnel-интерфейсов
exit data-plane     IPIP от роутеров до выбранного exit
policy plane        fwmark, uid rule и routing table 200
```

Infra overlay даёт защищённую связность между узлами. Babel отвечает за достижимость overlay-узлов и service prefixes. Пользовательский трафик, который должен выйти через exit, получает mark, попадает в table `200` и уходит в активный IPIP-интерфейс.

`exit-route.sh` каждые `EXIT_ROUTE_INTERVAL` секунд проверяет Babel-достижимость exit marker-prefixes, выбирает первый reachable exit из `exit_order` и синхронизирует route в table `200`. Если ни один exit не reachable, `network.exit200.disabled=1`, и policy route не применяется.

## Структура репозитория

```text
config.json                         декларативное описание сети
routers/example/                    OpenWrt overlay-шаблон
servers/example/                    Linux exit-server шаблон
tools/default.py                    глобальные defaults и адресные пулы
tools/generate.py                   генератор mesh/exit/access configs
tools/validate.py                   проверка generated configs
tools/show_unmanaged.py             отчёт по ручным unmanaged-частям
build_router_images.py              сборка OpenWrt firmware через ImageBuilder
deploy_servers.py                   деплой generated server tree на exit-серверы
upgrade_routers.py                  загрузка sysupgrade-образов на роутеры
run_routers.py / run_servers.py     удалённые команды и версии
collect_link_speeds.py              directed iperf3-замеры
render_topology_2d.py               SVG topology renderer
render_topology_3d.py               интерактивная Three.js topology map
```

`routers/example` и `servers/example` являются шаблонами. Конкретные router- и server-директории создаются как lowercase slug рядом с шаблонами. Имена берутся из `config.json`.

```text
Spine01 -> routers/spine01/
Leaf01  -> routers/leaf01/
EGR01   -> servers/egr01/
REV01   -> servers/rev01/
```

## Предусловия

На build/deploy-машине нужны:

```text
python3
git
ssh, scp, ssh-keygen
age, age-keygen
wg
openssl
apk / apk-tools
wget
tar с поддержкой zst
make
```

Для измерения скорости линков дополнительно нужны `iperf3` и `jq` на узлах, где запускаются замеры.

На exit-серверах используются Linux, systemd, root-доступ, AmneziaWG tooling, Babel и ipset/nftables tooling, которые вызывают generated scripts.

## Быстрый рабочий цикл

```bash
# 1. Описать сеть
vim config.json

# 2. Сгенерировать router/server configs, keys, SSH aliases и проверки
./generate_configs.py

# 3. Задеплоить exit-серверы
./deploy_servers.py

# 4. Собрать OpenWrt images
./build_router_images.py

# 5. Посмотреть собранные образы
ls -lh images/

# 6. Обновить роутеры выбранным git-short-hash из имени образа
./upgrade_routers.py <git-short-hash>

# 7. Проверить версии
./run_routers.py
./run_servers.py

# 8. Замерить links и отрисовать topology
./collect_link_speeds.py --progress --json-out link-speeds.json
./render_topology_2d.py --speeds-json link-speeds.json --main-label-mode problems
./render_topology_3d.py --speeds-json link-speeds.json
```

Для локальной проверки без скачивания AWG packages и без синхронизации per-router package repositories:

```bash
./generate_configs.py --skip-awg-download --skip-package-sync
```

## `config.json`

Основные top-level keys:

```text
name
ssh_key_dir
secret_key
openwrt_version
packages
device_profiles
main_router
routers
mesh_hubs
exit_hubs
exit_order
access
```

Минимальная форма выглядит так:

```json
{
  "name": "example-mesh",
  "ssh_key_dir": ".ssh",
  "secret_key": "age1...",
  "openwrt_version": "25.12.4",
  "packages": ["babeld", "curl", "ip-full"],

  "device_profiles": {
    "asus_rt-ax59u": {
      "board": "mediatek/filogic",
      "arch": "aarch64_cortex-a53"
    }
  },

  "main_router": "Spine01",

  "routers": [
    {
      "name": "Spine01",
      "device_profile": "asus_rt-ax59u",
      "subnet": "10.101.1.0/24"
    }
  ],

  "mesh_hubs": [
    {
      "name": "Spine01",
      "listen_ip": "203.0.113.11"
    }
  ],

  "exit_hubs": [
    {
      "name": "EGR01",
      "listen_ip": "198.51.100.21",
      "exit_ip": "198.51.100.121"
    }
  ],

  "access": {}
}
```

### `routers`

`routers` описывает OpenWrt-устройства.

Частые поля:

- `name` - имя узла;
- `device_profile` - профиль из `device_profiles`;
- `subnet` - LAN-сеть роутера, обычно `/24`;
- `packages` - per-router добавление или удаление пакетов;
- `wifi_2g`, `wifi_5g` - Wi-Fi параметры;
- `allow_to_router` - каким source-сетям разрешён INPUT на target-роутер;
- `allow_to_lan` - каким source-сетям разрешён FORWARD в LAN target-роутера;
- `exit_order` - индивидуальный приоритет exit-серверов.

`allow_to_router` и `allow_to_lan` задаются на source-роутере или access-группе, но firewall rules создаются на target-роутере.

```json
{
  "name": "Leaf01",
  "subnet": "10.101.11.0/24",
  "allow_to_router": ["Spine01"]
}
```

В текущем `config.json` это значит, что LAN `Leaf01` может обращаться к самому роутеру `Spine01`. Для FORWARD в LAN target-роутеров используется `allow_to_lan`; например `Leaf04` разрешает LAN-доступ к `Spine01` и `Leaf01`.

### `mesh_hubs`

`mesh_hubs` добавляет публичную endpoint-роль к router-узлу.

```json
{
  "name": "Spine01",
  "listen_ip": "203.0.113.11"
}
```

Обычный `mesh_hub` работает как spine/core: он принимает infra AmneziaWG-линки от leaf-роутеров, других spine и exit-серверов. Узел с `access_only=true` принимает access-группы, но не становится transit spine для infra mesh.

### `exit_hubs`

`exit_hubs` описывает Linux exit-серверы.

```json
{
  "name": "EGR01",
  "listen_ip": "198.51.100.21",
  "exit_ip": "198.51.100.121"
}
```

Поддерживаемые варианты:

| Config | Смысл |
|---|---|
| `name` | reverse/internal exit без публичного endpoint |
| `name + listen_ip` | public exit, принимающий AWG-связи |
| `name + listen_ip + exit_ip` | public exit с отдельным SNAT-адресом |

`listen_ip` - адрес для tunnel peers. `exit_ip` - публичный egress-адрес для SNAT. Если `exit_ip` не задан, сервер использует MASQUERADE через default interface.

### `access`

`access` задаёт пользовательские входы в overlay.

Поддерживаемые протоколы:

- `wireguard`;
- `amneziawg`;
- `openvpn`.

Пример WireGuard access-группы:

```json
"access": {
  "Spine01": [
    {
      "name": "AdminWG",
      "protocol": "wireguard",
      "policy": "trusted",
      "port": 45110,
      "subnet": "10.201.1.0/24",
      "allow_to_router": ["all"],
      "allow_to_lan": ["all"],
      "users": ["AdminLaptop", "AdminPhone"]
    }
  ]
}
```

Access-группа размещается на router-узле с публичным endpoint: обычном `mesh_hub` или `access_only` hub.

Политики:

| Policy | Firewall zone | Поведение |
|---|---|---|
| `trusted` | `TrustedAccess` | Доступ задаётся через `allow_to_router` и `allow_to_lan`; может использовать exit policy |
| `transit` | `TransitAccess` | Клиентский трафик в основном уходит через exit; доступ к router/LAN остаётся явным |

Для OpenVPN access генератор создаёт:

```text
files/etc/config/openvpn
files/etc/openvpn/<AccessName>/server.ovpn
files/etc/openvpn/<AccessName>/ca/ca.key
files/etc/openvpn/<AccessName>/ca/ca.pem
files/etc/openvpn/<AccessName>/clients/<User>.ovpn
```

Если у роутера есть OpenVPN access-группы, генератор добавляет в `customization()` managed hotplug-скрипт `/etc/hotplug.d/iface/99-babeld-openvpn`. Он перезапускает `babeld`, когда generated OpenVPN access interface поднимается через `ifup`, чтобы Babel увидел новый интерфейс.

### `device_profiles`

`device_profiles` связывает короткое имя профиля с OpenWrt target/subtarget и apk arch:

```json
"device_profiles": {
  "asus_rt-ax59u": {
    "board": "mediatek/filogic",
    "arch": "aarch64_cortex-a53"
  }
}
```

`board` используется для выбора OpenWrt ImageBuilder. `arch` используется для AWG `.apk` packages.

### Packages

Глобальные `packages` пишутся без префиксов. Per-router overrides используют `+` и `-`:

```json
{
  "name": "Spine01",
  "packages": ["+luci-proto-wireguard"]
}
```

```json
{
  "name": "Leaf02",
  "packages": ["-block-mount", "-kmod-fs-vfat", "-kmod-usb-storage", "-tcpdump"]
}
```

Для generated конфигов обычно нужны runtime packages для Babel, AWG/IPIP, DoH, curl и служебных проверок. Для WireGuard/OpenVPN access добавляются соответствующие пакеты на конкретные роутеры.

### Wi-Fi

```json
"wifi_5g": {
  "ssid": "Example-5G",
  "key": "ROUTER_SECRET_V1{...}",
  "blocked_macs": ["aa:bb:cc:dd:ee:ff"]
}
```

Если Wi-Fi-блок не задан, соответствующее radio/interface отключается в bootstrap customization.

## Generated outputs

После `./generate_configs.py` для каждого router создаётся дерево вида:

```text
routers/<router-slug>/
  files/etc/config/network_part
  files/etc/config/firewall_part
  files/etc/config/babeld
  files/etc/config/openvpn
  files/etc/wireguard/<AccessName>/clients/*.conf
  files/etc/openvpn/<AccessName>/server.ovpn
  files/etc/openvpn/<AccessName>/clients/*.ovpn
  files/etc/dropbear/authorized_keys
  files/etc/router-autoinstall.env
  files/etc/ipsets/direct-static.txt
  files/etc/ipsets/direct.txt
  files/etc/scripts/*.sh
  files/etc/init.d/*
  files/etc/crontabs/root
  packages/*.apk
```

Для каждого exit из `exit_hubs` создаётся lowercase-директория:

```text
servers/<exit-slug>/
  etc/awg-server.env
  etc/amnezia/amneziawg/*.conf
  etc/babel<exit-slug>.conf
  etc/ipsets/direct-static.txt
  etc/ipsets/direct.txt
  etc/systemd/system/*.service
  etc/systemd/system/*.timer
  root/deploy.sh
  root/.ssh/authorized_keys
```

На exit-серверах runtime env для `awg-server.sh`, включая direct-list refresh settings и `BABELD_CONF`, находится в `etc/awg-server.env`.

## Templates, managed-секции и `customization()`

Некоторые файлы сшиваются по marker-строке:

```text
# Unique part up to this line
```

Всё выше marker-а является локальной частью конкретного узла. Всё ниже marker-а синхронизируется из шаблона.

Это касается:

- `files/etc/config/network_part`;
- `files/etc/config/firewall_part`;
- `files/etc/uci-defaults/99-firstboot-custom`.

`99-firstboot-custom` содержит функцию:

```sh
customization() {
    # Set subnet and name
    true
}
```

Генератор обновляет внутри неё managed-блоки для LAN IP, hostname, DoH source address, Wi-Fi и OpenVPN/Babel hotplug, если на роутере есть OpenVPN access interfaces. Остальную router-specific логику можно добавлять туда же: UCI-настройки, sysctl, init enable, локальные хаки под конкретное железо.

`customization()` выполняется на роутере при первом запуске образа, после общей подготовки и перед `uci commit`.

`tools/show_unmanaged.py` запускается после генерации и показывает unmanaged-контент, который переживает `tools/generate.py`: ручные UCI-блоки в `network_part` и `firewall_part`, ручные части внутри `customization()` и лишние файлы вне generated/sync-managed набора. Generated UCI-блоки в `network_part` и `firewall_part`, а также generated-блоки внутри `customization()` скрываются из отчёта только если они совпадают с тем, что строит генератор. Полностью generated-файлы, которые генератор перезаписывает целиком, не используются как standalone drift-check: ручные правки в них перезаписываются генерацией.

Проверка неожиданных unmanaged-частей:

```bash
./tools/show_unmanaged.py
./tools/show_unmanaged.py --details
```

Если unmanaged-контент есть, команда печатает короткий hash отчёта:

```text
unmanaged-sha256: 23515a3
```

С `--details` после hash печатается сам отчёт. Если unmanaged-контента нет, команда печатает только:

```text
No unmanaged content found.
```

В этом случае `unmanaged-sha256` не печатается.

## Что делает `99-firstboot-custom`

Bootstrap-скрипт на OpenWrt:

- сшивает `network_part`, `dhcp_part` и `firewall_part` с реальными UCI-файлами;
- настраивает `https-dns-proxy` и dnsmasq;
- создаёт пользователя и группу `doh` с uid/gid `4453`;
- увеличивает log buffer;
- ставит timezone;
- отключает HTTPS listener LuCI на `443`;
- отключает autostart `wan6`;
- применяет DHCP client-id workaround для OpenWrt 25.12;
- переносит deploy/build version в OpenWrt release files;
- выполняет `customization()`;
- делает `uci commit`.

## Секреты

Секреты хранятся в исходном дереве как `ROUTER_SECRET_V1{...}` и расшифровываются только во временной staging/build/deploy-директории.

Типичный подход:

```bash
# Создать age key
age-keygen -o secret.key

# Зашифровать строку для config.json
printf '%s' 'plain-secret' | age -r <recipient> -a
```

`secret_key` в `config.json` указывает ключ для расшифровки. Generated configs сохраняют encrypted marker в исходном дереве, а runtime plaintext появляется только на стадии сборки или деплоя.

## Команды

### `generate_configs.py`

Главная команда генерации.

```bash
./generate_configs.py
./generate_configs.py --config prod.json
./generate_configs.py --skip-awg-download --skip-package-sync
./generate_configs.py --skip-hooks
./generate_configs.py --force
```

Что делает:

1. читает и валидирует `config.json`;
1. создаёт `routers/<slug>` из `routers/example`;
1. скачивает AWG2 `.apk`, если не указан `--skip-awg-download`;
1. синхронизирует per-router `packages/`, если не указан `--skip-package-sync`;
1. синхронизирует шаблонные файлы из `routers/example`;
1. запускает `tools/generate.py`;
1. запускает `tools/ensure_ssh_keys.py`;
1. запускает `tools/validate.py`;
1. запускает `tools/show_unmanaged.py`.

`--force` передаётся в `tools/generate.py` и пересоздаёт mesh/exit WG/AWG keys. Access secrets сохраняются.

`--skip-hooks` пропускает `tools/generate.py`, `tools/ensure_ssh_keys.py`, `tools/validate.py` и `tools/show_unmanaged.py`.

### `tools/generate.py`

Низкоуровневый генератор mesh/exit/access configs.

```bash
./tools/generate.py
./tools/generate.py --config prod.json
./tools/generate.py --force
./tools/generate.py --verbose
```

Он генерирует infra mesh, exit links, access groups, Babel config, firewall parts, bootstrap managed-блоки и runtime env files.

### `tools/validate.py`

Проверяет консистентность generated mesh/exit/access configs после генерации: наличие expected файлов, stale dirs/files, ключи, сертификаты, OpenVPN UCI, firewall, routing и порты.

```bash
./tools/validate.py
./tools/validate.py --config prod.json -v
```

### `deploy_servers.py`

Копирует generated server tree на exit-серверы через `scp` и запускает `/root/deploy.sh`.

```bash
./deploy_servers.py
./deploy_servers.py EGR01 REV01
./deploy_servers.py --server-ssh-mode node REV02
./deploy_servers.py --replace-authorized-keys
./deploy_servers.py --ssh-connect-timeout 10
```

`--server-ssh-mode auto` сначала пробует node alias, затем public alias. Для первого деплоя public exit может требовать `--server-ssh-mode public`.

### `build_router_images.py`

Собирает OpenWrt firmware через ImageBuilder.

```bash
./build_router_images.py
./build_router_images.py Spine01
./build_router_images.py Spine01,Leaf01 --version 25.12.4
```

Результат складывается в `images/`:

```text
images/<router-slug>_<openwrt-version>_<git>_<timestamp>_sysupgrade.bin
images/<router-slug>_<openwrt-version>_<git>_<timestamp>_factory.bin
```

Encrypted secrets расшифровываются только во временной ImageBuilder-директории.

### `upgrade_routers.py`

Копирует `sysupgrade`-образы из `images/` на роутеры и после подтверждения запускает async `sysupgrade -n`.

```bash
./upgrade_routers.py e47e68e
./upgrade_routers.py e47e68e Spine01 Leaf01
./upgrade_routers.py e47e68e --result-dir images --remote-dir /tmp
```

Порядок обновления:

```text
leaf routers -> mesh hubs except main_router -> main_router
```

### `run_routers.py`

Запускает команду на роутерах в upgrade-порядке.

```bash
./run_routers.py
./run_routers.py uptime
./run_routers.py 'ubus call system board'
```

Если команда не указана, показывает OpenWrt version из `/etc/os-release`.

### `run_servers.py`

Запускает команду на exit-серверах.

```bash
./run_servers.py
./run_servers.py --servers EGR01,REV02 uptime
./run_servers.py --server-ssh-mode node 'systemctl status awg-server-network'
```

Если команда не указана, читает `/etc/deploy_version`.

## Проверка скорости линков

`collect_link_speeds.py` собирает directed iperf3-замеры для router-router, router-exit и exit-exit links.

```bash
# Посмотреть матрицу целей без запуска iperf3
./collect_link_speeds.py --list-targets

# Собрать таблицу
./collect_link_speeds.py --progress

# Сохранить JSON для renderer-а
./collect_link_speeds.py --progress --json-out link-speeds.json
```

Полезные опции:

```bash
--topology-source generated
--topology-source config
--iperf-time 3
--iperf-bitrate 50M
--format table|tsv|json
--server-ssh-mode auto|node|public
```

`generated` читает реальные generated AWG/UCI files. `config` строит плановую topology из `config.json`.

## Рендер topology

SVG-карты:

```bash
./collect_link_speeds.py --progress --json-out link-speeds.json
./render_topology_2d.py --speeds-json link-speeds.json
./render_topology_2d.py --topology-only --topology-source config --out topology.svg
./render_topology_2d.py --only overview
./render_topology_2d.py --main-label-mode problems
```

По умолчанию для speed view создаются:

```text
topology_speed_from.svg
topology_speed_to.svg
```

Интерактивная 3D-карта:

```bash
./render_topology_3d.py --speeds-json link-speeds.json --out topology_3d.html
./render_topology_3d.py --topology-only --topology-source generated
./render_topology_3d.py --topology-only --topology-source config
```

## Полезные проверки

```bash
# Python syntax
python3 -m py_compile *.py tools/*.py

# Валидация generated config
./tools/validate.py

# Отчёт по unmanaged sections/files
./tools/show_unmanaged.py --details

# Remote versions
./run_routers.py
./run_servers.py

# Failed systemd units на exit-ах
./run_servers.py 'systemctl --failed'
```

## Что важно помнить

- `routers/example` и `servers/example` - шаблоны, а не целевые узлы.
- Router directories всегда lowercase: `routers/spine01`, `routers/leaf01`.
- Server directories тоже всегда lowercase: `servers/egr01`, `servers/rev01`.
- `allow_to_router` разрешает INPUT на target-роутер.
- `allow_to_lan` разрешает FORWARD в LAN target-роутера.
- `exit_order` задаёт приоритет выхода, но не адресацию.
- Если все exit недоступны, `exit-route.sh` ставит `network.exit200.disabled=1`, и трафик возвращается на main default path.
- Reverse exit без `listen_ip` доступен через generated node-IP после bootstrap.
- `server_<exit>_node` - overlay alias, `server_<exit>` - public/bootstrap alias.
- `--force` пересоздаёт mesh/exit tunnel keys; access secrets сохраняются.
- Router-specific логику удобно добавлять в `customization()` внутри `99-firstboot-custom`.
