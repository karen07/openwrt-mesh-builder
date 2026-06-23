# Краткое описание diff

## Что изменено

- Убрана зависимость получения metadata `.apk` от `apk-tools`: имя, версия и arch пакета читаются напрямую из ADB/APK v3 формата на чистом Python.
- Добавлена нативная генерация и проверка WireGuard/AmneziaWG ключей через X25519 на Python вместо вызовов `wg genkey` и `wg pubkey`.
- Заменены отдельные локальные команды на Python stdlib:
  - `clear` заменён ANSI escape-последовательностью;
  - `git rev-parse --short HEAD` заменён чтением `.git/HEAD`, refs и `packed-refs`;
  - `wget` заменён `urllib`;
  - `tar` заменён `tarfile`;
  - запуск соседних Python-скриптов через subprocess заменён in-process вызовом `main()`.
- Исправлена ошибка скачивания HTTPS-файлов с `CERTIFICATE_VERIFY_FAILED`: download paths используют общий helper с unverified SSL context.

## Что осталось внешним

Оставлены внешние инструменты, для которых нет совместимого аналога в стандартной библиотеке Python без большой отдельной реализации:

- `make` для OpenWrt ImageBuilder;
- `ssh`/`scp` для удалённого деплоя;
- `openssl` для X.509/OpenVPN certificates;
- `age`/`age-keygen` для текущего формата secrets;
- `ssh-keygen` для OpenSSH ключей.

## Тесты

Добавлены regression-тесты для:

- APK metadata parsing без `apk-tools`;
- X25519/WireGuard ключей без `wg`;
- чтения git short hash без команды `git`;
- SSL download helper.

