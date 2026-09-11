# План реализации

Приоритет имеет UPDATE в PROMT.md: никакой интеграции публикации и TikTok OAuth.

1. FastAPI + SQLAlchemy/Alembic; PostgreSQL persistent queue; отдельный runner.
2. Research через OpenAI Responses web search → проверенные URL и выдержки → Pydantic JSON → отдельная проверка фактов.
3. Pexels API, реестр прав, Edge TTS, ASS, FFmpeg 1080×1920; четыре выходных файла.
4. Защищённый API, n8n manual/schedule workflows, Docker Compose/Dokploy.
5. Unit/integration tests и настоящий FFmpeg smoke test на синтетических fixtures.
6. README на русском с запуском, секретами, скачиванием, backup и ограничениями; отправка в предоставленный GitHub при доступной авторизации.

Решения: одна последовательная render-очередь (1–3 видео в день), PostgreSQL advisory lock для одного runner, повтор незавершённых задач после рестарта с ограничением попыток. Отдельные базы и пользователи n8n/app. Mock режим только явно помеченные тестовые материалы; публикации отсутствуют во всех режимах.
