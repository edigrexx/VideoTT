# Проверки MVP

Дата: 2026-09-11.

## Выполнено локально

- Python 3.12.14; Ruff — без ошибок; `pip check` — без конфликтов.
- **42 tests passed**, в том числе реальный PostgreSQL 16.10. Проверены upgrade → downgrade → upgrade Alembic, UUID/timestamptz, SKIP LOCKED и advisory lock, повторы и устаревшие попытки, API authentication/Range download/idempotency, JSON parsing, factual gate, лицензии, Pexels responses и ограничения загрузок, официальный OpenAI SDK с mock HTTP transport.
- Полный offline smoke: persistent job → 9 synthetic scenes → audio → ASS → FFmpeg → четыре файла → READY. Итог: **1080×1920, 30 fps, H.264/AAC, 75.20 s**. Извлечённый кадр осмотрен: текст читаем, две строки, достаточный нижний отступ.
- Отдельный сквозной тест **реального FastAPI + runner + PostgreSQL**: runner остановлен SIGTERM во время RENDERING, задание осталось в БД, после запуска завершилось READY со второй попытки. Final MP4 успешно скачан через защищённый HTTP endpoint.
- Реальная безопасная загрузка публичной HTML-страницы с DNS pinning и TLS SNI прошла.
- Реальный Edge TTS произнёс короткую тестовую фразу и вернул **6 word timing cues**.
- Экспорты n8n проверены как JSON, с авторизацией, ограниченным polling и без вызовов публикации.
- GitHub Actions run `34573468161` прошёл полностью: Docker-образ собран на Ubuntu, production Compose поднят в offline fixture mode, job доведён до READY через HTTP API, оба workflow проверены внутри n8n-контейнера.

Для FFmpeg smoke на Mac использован отдельный FFmpeg с libass в локальном venv: системный FFmpeg не поддерживал ASS. Для PostgreSQL — переносимые бинарники в игнорируемой `.artifacts/`, системная установка не изменялась.

## Что ещё требует внешней среды

- На этом Mac Docker отсутствует; Linux Docker build и контейнерные тесты вынесены в `.github/workflows/ci.yml`. Production Compose уже проверен в GitHub Actions для коммита `2955c2c`.
- Live OpenAI research + Pexels footage пока не запускались: реальные API-ключи пользователя не предоставлены. Структура запросов проверена по документации и mocked tests; это не подтверждение качества реальных сценариев или релевантности stock.
- Импорт и запуск workflows в вашей n8n, DNS/HTTPS и сам Deploy в вашем Dokploy выполняются после внесения Environment. Доступ к вашему серверу не предоставлен.
- Offline MP4 содержит тестовый фон и тон, явно помечен TEST FIXTURE. Он проверяет технический конвейер и не предназначен для публикации.

## Повторить

`make test` запускает disposable PostgreSQL, тесты и настоящий FFmpeg smoke в Docker. `make first-video` после настройки реальных ключей проверяет production pipeline. Инструкция по ручному скачиванию и диагностике — в README.
