# Покрытие режимов конфигурации (демо)

Этот проект содержит пример `config.json`, специально составленный так, чтобы **каждый
вариант, доступный через JSON-конфигурацию на момент этой версии генератора**, был
представлен хотя бы один раз. Не путать с рабочим production-конфигом:
используются демонстрационные IP-адреса, пароли и ключ защиты заголовка.

Проверить пример без сетевых запросов, образов OpenWrt и запуска генерации можно так:

```sh
./check_config_coverage.py
```

Checker читает **текущие** множества разрешённых ключей и режимов из
`tools/config_schema.py`, `tools/awg_model.py`, `tools/default.py` и
`tools/generate_runtime.py`, собирает модель через `build_config_data()` и
сериализует EXIT UCI. При добавлении нового ключа или режима он завершится с
ошибкой, пока демонстрационный `config.json` не будет дополнен.

## Режимы `routing_rules` (6/6)

Все представлены у `Spine01` (строго по одному IP `/32` на правило):

| mode | IP | EXIT |
| --- | --- | --- |
| `direct` | `10.101.1.50/32` | отсутствует |
| `auto` | `10.101.1.51/32` | отсутствует |
| `split_fail_open` | `10.101.1.52/32` | `EGR01` |
| `split_fail_closed` | `10.101.1.53/32` | `EGR02` |
| `exit_fail_open` | `10.101.1.54/32` | `PUB01` |
| `exit_fail_closed` | `10.101.1.55/32` | `EGR02` |

`direct` / `auto` запрещают параметр `exit`; четыре фиксированных режима требуют его.

## Режимы `exit_route` (6/6 + implicit default)

| Роутер | Глобальный mode | Дополнительные параметры |
| --- | --- | --- |
| `Spine01` | `AUTO` | `auto_exit` со списком предпочтительных EXIT |
| `Spine02` | `DIRECT` | без `exit` |
| `Spine03` | `SPLIT_FAIL_OPEN` | `exit: EGR01` |
| `AccessOnly01` | `SPLIT_FAIL_CLOSED` | `exit: EGR02` |
| `AccessOnly02` | `EXIT_FAIL_OPEN` | `exit: PUB01` |
| `Leaf01` | `EXIT_FAIL_CLOSED` | `exit: REV01` |
| `Leaf02`, `Leaf03`, `Leaf04` | *не задан* -> `AUTO` | fallback схемы |

В отличие от `routing_rules`, глобальные значения mode - **в верхнем регистре**.

## Протоколы, политики и узловые роли

Все шесть сочетаний протокол x политика представлены:

| Протокол | trusted | transit |
| --- | --- | --- |
| `wireguard` | `Spine01/AdminWG` | `Spine01/GuestWG` |
| `openvpn` | `Spine02/OpsOVPN` | `Spine02/GuestOVPN` |
| `amneziawg` | `AccessOnly01/MobileAWG` | `AccessOnly01/PartnerAWG` |

Дополнительно `AccessOnly02/BackupMobileAWG` демонстрирует обязательные
базовые параметры AWG при отсутствии необязательных параметров AWG 3.x
(они вычисляются детерминированно). Пустой или полностью отсутствующий блок
`awg` **не поддерживается**: обязательны `jc`, `jmin`, `jmax`, `s1`-`s4` и
`h1`-`h4`. `PartnerAWG` показывает все 26 разрешённых параметров, включая
`header_protection_key` и `content_padding_addition`. Булевы значения
`random_trailers` и `disable_cookies` представлены в обоих состояниях.

Роли: `Spine01`/`Spine02`/`Spine03` - обычные `mesh_hub`,
`AccessOnly01`/`AccessOnly02` - `access_only: true`; `Leaf01`-`Leaf04` -
обычные leaf без публичного hub. Значения `access_only: false`, `true` и
пропущенный ключ (false по умолчанию) также показаны.

EXIT hub варианты:

- `EGR01`/`EGR02` - `listen_ip` + `exit_ip`: публичный выход с отдельным SNAT IP.
- `PUB01` - только `listen_ip`: публичный выход с MASQUERADE.
- `REV01`/`REV02` - только `name`: reverse/internal EXIT.

## Остальные варианты JSON-модели

| Возможность | Примеры |
| --- | --- |
| WAN DHCP | любой роутер без `pppoe`, например `Spine02` |
| PPPoE с явно заданным MTU | `Spine01`, `mtu: 1492` |
| PPPoE с MTU по умолчанию | `Leaf04` |
| Wi-Fi 2.4 / 5 / 6 ГГц | `wifi_2g`, `wifi_5g`, `wifi_6g` |
| Отключённое радио через отсутствие блока | `Leaf04` без Wi-Fi блоков |
| DHCP reservation без индивидуальных опций | `Spine01/NAS` |
| DHCP с DNS-only опциями | `Spine01/SmartTV`, `dhcp_options: ["6,..."]` |
| DHCP с несколькими индивидуальными опциями | `Spine01/Console`, коды `3` и `6` |
| ACL на сам роутер | `allow_to_router` (`Leaf01` с одним именем, `Spine01` со списком `all`) |
| ACL на удалённую LAN | `allow_to_lan` (`Leaf04` с несколькими именами, `Spine01` с `all`) |
| ACL внутри access-группы | `allow_to_router` и `allow_to_lan` в `AdminWG` / `MobileAWG` |
| Глобальная очередность EXIT | top-level `exit_order` - полный список |
| Порядок EXIT на конкретном роутере | `Spine01` и `Spine03` - разные подмножества/приоритеты |
| Порядок AUTO внутри `exit_route` | `Spine01.exit_route.auto_exit` |
| Глобальные user packages | top-level `packages` |
| Добавление и исключение пакетов на роутере | `Leaf02.packages`, варианты `+nano` и `-tcpdump` |
| Версия OpenWrt release и SNAPSHOT | top-level `25.12.6`, `Spine02` - `25.12-SNAPSHOT` |
| Несколько платформ и архитектур | `device_profiles` + ссылки `device_profile` |

Проверка по схеме даёт 100% использования **имён полей**: верхний уровень
11/11, роутер 16/16, access 9/9, AmneziaWG 26/26, плюс все ключи вложенных
объектов Wi-Fi, PPPoE, DHCP, mesh, exit и маршрутизации.

## Варианты CLI - это НЕ поля `config.json`

Режимы исполнения и визуализации нельзя "добавить в JSON", поскольку они
передаются флагами команды:

| Команда/флаг | Допустимые варианты |
| --- | --- |
| `deploy_servers.py`, `run_servers.py`, `collect_link_speeds.py --server-ssh-mode` | `auto`, `node`, `public` |
| `collect_link_speeds.py --format` | `table`, `tsv`, `json` |
| `collect_link_speeds.py --topology-source` | `generated`, `config` |
| `render_topology_2d.py --only` | `all`, `topology`, `from`, `to` |
| `render_topology_2d.py`, `render_topology_3d.py --topology-source` | `generated`, `config` |
| `build_router_images.py` (типы артефактов) | `factory`, `sysupgrade` - распознаются в именах готовых образов |
| `generate_configs.py` | обычная генерация, `--clean`, `--update-packages`, `--force`, `--skip-direct-downloads`, `--details` |

Это **не взаимоисключающие режимы JSON**. Чтобы протестировать их, нужны
отдельные CLI/integration-тесты; checker проверяет только конфигурационную
модель и сериализацию маршрутизации.

## Важные ограничения

1. **6 ГГц:** `Spine03.wifi_6g` включён ради иллюстрации схемы. Для его
   реального развёртывания требуется устройство с поддерживаемым OpenWrt
   `radio2` в диапазоне 6 ГГц; указанный профиль `asus_tuf-ax4200` не
   подтверждает наличие такого радио. Схема JSON не проверяет аппаратную
   совместимость `wifi_6g`.
1. **SNAPSHOT:** `25.12-SNAPSHOT` допустим синтаксически, но наличие нужного
   ImageBuilder/APK репозитория для выбранной версии отдельно не проверялось.
1. **Секреты:** `Example-*` и демонстрационный
   `header_protection_key` не использовать в реальной сети. Заменить на
   уникальные секреты или зашифрованные маркеры генератора.
1. **MAC filtering:** старого поля `blocked_macs` в схеме больше нет; вернуть
   его только изменением генератора, добавлением поля в JSON нельзя.
1. **Вне JSON:** списки `direct` (`EXIT_DIRECT_*`), параметры таймеров,
   адресные пулы и многое другое задаются в `tools/default.py`, а не в
   `config.json`.
1. `check_config_coverage.py` проверяет модель и режимы, **не выполняет**
   сетевую генерацию, сборку образов, развёртывание или validation готовых UCI.
