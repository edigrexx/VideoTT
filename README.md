# VideoTT

Тема → проверяемые источники → оригинальный английский сценарий → Pexels → озвучка → субтитры → готовый вертикальный MP4.

**Публикуете вы сами.** TikTok API, OAuth, автозагрузка, музыка и скачивание чужих роликов не реализованы — согласно последнему UPDATE в `PROMT.md`. TikTok Developer credentials не нужны.

Для каждого успешного задания:

```text
/data/media/output/{video_id}/
├── final.mp4              # 1080×1920, 30 fps, H.264/AAC, 60–90 секунд
├── caption.txt            # описание + 3–6 хэштегов
├── metadata.json          # тема, заголовок, длительность, источники
└── rights_manifest.json   # авторы, лицензии, ссылки и SHA-256 клипов
```

Videos provided by [Pexels](https://www.pexels.com). Авторы каждого использованного клипа записываются в manifest.

## Что потребуется

- Ваш Linux-сервер с Dokploy и Docker Compose v2. Один проект — один последовательный обработчик. GPU не нужен.
- Практический начальный размер сервера: 4 CPU, 8 GB RAM, 40+ GB свободного диска. Это ориентир для этого конвейера, скорость зависит от CPU и клипов. FFmpeg ограничен двумя потоками по умолчанию.
- Исходящий интернет: OpenAI, Pexels/CDN, публичные страницы источников, сервис озвучки Microsoft.
- **Pexels API key**, **OpenAI API key**, **название модели OpenAI** с поддержкой Responses API, `web_search` и Structured Outputs. Подписка ChatGPT сама по себе не заполняет API-ключ этого приложения.

### Получить внешние ключи

1. Зарегистрируйтесь на [Pexels API](https://www.pexels.com/api/), создайте API key для своего проекта. Запишите его в `PEXELS_API_KEY`.
2. Откройте [OpenAI API keys](https://platform.openai.com/api-keys), создайте серверный ключ проекта и настройте API billing/лимит расходов. Запишите ключ в `LLM_API_KEY`.
3. В примере уже стоит `LLM_MODEL=gpt-5.6-luna`: [документация модели](https://developers.openai.com/api/docs/models/gpt-5.6-luna) подтверждает web search и Structured Outputs. Проверьте доступность **вашему API-проекту** или укажите другую модель с этими возможностями. Названия моделей в Python-коде не зашиты. Проверяйте доступность в [каталоге моделей](https://developers.openai.com/api/docs/models). Исследование использует платный веб-поиск и несколько запросов к модели.
4. Edge TTS отдельного ключа не требует. По умолчанию используется `en-US-AriaNeural`.

## Быстрая проверка без ключей

На машине с Docker, из отдельной тестовой копии репозитория:

```bash
git clone https://github.com/edigrexx/VideoTT.git
cd VideoTT
python3 scripts/setup_env.py --test-mode
docker compose up -d --build
make first-video
make list
```

`setup_env.py` создаёт `.env` с пятью разными случайными секретами, правами `0600` и никогда не перезаписывает существующий файл. Можно вместо этого сделать `cp .env.example .env`, но тогда случайные секреты нужно заполнить самостоятельно.

В тестовом режиме работают только тема **Why do the F and J keys on keyboards have raised bumps?** и синтетические fixtures: цветные сцены, тихий тестовый тон, надпись `TEST FIXTURE`, `is_test=true` в метаданных. Это проверка монтажа, очереди и скачивания; это **не готовый ролик для публикации** и не проверка внешних API.

Для перехода к настоящим видео заполните внешние ключи и измените:

```dotenv
LLM_PROVIDER=openai
STOCK_PROVIDER=pexels
TTS_PROVIDER=edge
ALLOW_TEST_MODE=false
```

Затем `docker compose up -d --build`. Сначала дождитесь завершения старых тестовых заданий; уже поставленное задание нельзя незаметно перевести между mock и production.

## Настройка в Dokploy — пошагово

1. **Подготовьте переменные на своём компьютере.** В папке проекта выполните `python3 scripts/setup_env.py`. Откройте полученный `.env`, заполните `PEXELS_API_KEY`, `LLM_API_KEY`, `LLM_MODEL`. Секреты не отправляйте в GitHub.
2. **В Dokploy создайте Project**, например `VideoTT`, затем сервис **Docker Compose**. Выбирайте обычный Compose, не Stack/Swarm.
3. **Подключите Git**: репозиторий `https://github.com/edigrexx/VideoTT.git`, ветка `main`, путь к Compose `./docker-compose.yml`. Для приватного репозитория подключите GitHub App/доступ к репозиторию в Dokploy.
4. **Environment**: вставьте содержимое вашего `.env`. Обязательные значения перечислены ниже. `DATABASE_URL` оставьте пустым: приложение само подключится к своему PostgreSQL.
5. **Deploy.** Сначала поднимется PostgreSQL; одноразовый сервис `migrate` применит Alembic; затем стартуют `worker`, `runner`, `n8n`. Завершённый `migrate` с кодом **0** — нормальное состояние. Не нужно запускать миграции вручную при первом старте.
6. Проверьте логи. У `postgres`, `worker`, `runner`, `n8n` должны пройти healthchecks. Первая сборка загружает Python-пакеты, FFmpeg и шрифт.
7. Выберите способ доступа ниже. Для домашнего/локального сервера проще начать с **SSH-туннеля**, без домена и проброса портов на роутере.

### Доступ только из вашей сети: SSH-туннель

Compose слушает HTTP только на `127.0.0.1` сервера. Адрес `http://IP_СЕРВЕРА:8000` с другого компьютера поэтому не откроется — это ожидаемо.

На вашем компьютере:

```bash
ssh -N -L 5678:127.0.0.1:5678 -L 8000:127.0.0.1:8000 your-user@SERVER_IP
```

Оставьте терминал открытым, затем откройте:

- **n8n:** [http://localhost:5678](http://localhost:5678) — при первом входе создайте owner account.
- **VideoTT API:** [http://localhost:8000/docs](http://localhost:8000/docs) — браузер попросит логин **videott** и пароль **значение `WORKER_API_KEY`**.

Настройки `N8N_HOST=localhost`, `N8N_PROTOCOL=http`, `N8N_PUBLIC_URL=http://localhost:5678/`, `N8N_SECURE_COOKIE=false` подходят для этого способа. Не открывайте эти HTTP-порты в интернет.

Если локальные порты компьютера заняты, используйте другие левые порты в SSH-команде; для n8n также согласуйте `N8N_PUBLIC_URL` с адресом браузера. Если порты заняты на сервере, измените `N8N_LOCAL_PORT` / `WORKER_LOCAL_PORT` и правую сторону туннеля.

### Доступ через домены Dokploy

Если у вас есть настроенные домен/DNS и HTTPS:

1. В **Domains → Add Domain** добавьте `n8n.example.com`, сервис **n8n**, контейнерный порт **5678**, путь `/`, HTTPS.
2. При необходимости добавьте `video.example.com`, сервис **worker**, порт **8000**, путь `/`, HTTPS. API остаётся защищённым ключом. Домен worker не требуется для работы n8n.
3. В Environment измените:

```dotenv
N8N_HOST=n8n.example.com
N8N_PROTOCOL=https
N8N_PUBLIC_URL=https://n8n.example.com/
N8N_SECURE_COOKIE=true
N8N_PROXY_HOPS=1
```

4. В **Preview Compose** проверьте, что Dokploy добавил маршрутизацию к нужным сервисам и сохранил их сеть `backend`: `n8n` должен видеть `worker` и `postgres`. Затем повторите Deploy. Метки Traefik вручную обычно не нужны; [официальная инструкция Dokploy](https://docs.dokploy.com/docs/core/docker-compose/domains).
5. Откройте `https://video.example.com/docs`, логин `videott`, пароль `WORKER_API_KEY`.

Для сервера за домашним NAT публичный сертификат/домен не появляется автоматически. Пока DNS и входящий доступ не настроены, используйте SSH-туннель; пробрасывать PostgreSQL наружу не нужно.

## Какие ENV действительно заполнять

| Переменная | Что поставить |
|---|---|
| `POSTGRES_PASSWORD` | Случайный пароль администратора БД; генерируется setup_env.py |
| `POSTGRES_APP_PASSWORD` | Другой случайный пароль БД приложения; генерируется |
| `POSTGRES_N8N_PASSWORD` | Другой случайный пароль БД n8n; генерируется |
| `WORKER_API_KEY` | Ключ входа в API, минимум 32 символа; генерируется |
| `N8N_ENCRYPTION_KEY` | Постоянный ключ шифрования n8n; генерируется, сохраните резервную копию |
| `PEXELS_API_KEY` | Ваш ключ Pexels |
| `LLM_API_KEY` | Ваш ключ OpenAI API |
| `LLM_MODEL` | По умолчанию gpt-5.6-luna; проверьте доступ API-проекта |
| `N8N_HOST`, `N8N_PROTOCOL`, `N8N_PUBLIC_URL`, `N8N_SECURE_COOKIE` | Менять только при настройке домена |

Остальные параметры имеют значения в `.env.example`. `TIMEZONE=Asia/Almaty`; `TTS_VOICE` меняет голос. `MAX_ASSET_SIZE_MB=120` ограничивает **один** скачиваемый клип; `MAX_VIDEO_DURATION_SEC=90` — длительность результата; `MAX_DOWNLOAD_RETRIES=3` — максимум попыток загрузки; `MAX_JOB_ATTEMPTS=3` — попытки после перезапуска runner; `MAX_QUEUED_JOBS=20` — предел активных заданий. Встроенные таймауты и FFmpeg-потоки также настраиваются через ENV.

`MEDIA_ROOT` внутри Compose фиксирован `/data/media`. `DATABASE_URL` нужен только для собственной PostgreSQL-конфигурации. В `AUTO_UPLOAD_TIKTOK`, токенах и переменных `TIKTOK_*` необходимости нет: публикации отсутствуют.

**Не меняйте DB-пароли и N8N_ENCRYPTION_KEY при каждом Deploy.** Init-скрипт PostgreSQL запускается только на новом volume; изменение ENV само по себе пароль существующего пользователя не изменяет.

## Создать первый настоящий ролик

После настройки ключей и успешного запуска:

1. Откройте `/docs` с логином `videott` и паролем `WORKER_API_KEY`.
2. Найдите **POST /api/v1/videos → Try it out**.
3. В теле запроса оставьте:

```json
{
  "topic": "Why do the F and J keys on keyboards have raised bumps?"
}
```

4. Нажмите **Execute**. Ответ `202` с `job_id` / `video_id` означает, что запрос принят в очередь.
5. Через **GET /api/v1/jobs/{job_id}** проверяйте статус. Конвейер может занять несколько минут, особенно первый рендер.
6. Дождитесь `READY`. Через **GET /api/v1/videos/{video_id}** можно посмотреть сценарий, исследование, источники и результат проверки фактов.
7. Откройте `/api/v1/videos/{video_id}/download` в том же браузере, скачайте MP4. Аналогично `/caption`, `/metadata`, `/manifest`.
8. Просмотрите видео, проверьте утверждения и соответствие видеоряда. Загрузите MP4 в TikTok вручную и вставьте описание из `caption.txt`.

Swagger UI использует стандартные CDN-ресурсы и требует интернет в браузере. Авторизация API также поддерживает `Authorization: Bearer <WORKER_API_KEY>` для n8n и CLI.

Альтернатива из каталога Compose на сервере:

```bash
make first-video
make list
# Вставьте фактический UUID:
docker compose exec worker python scripts/client.py get --id VIDEO_UUID
```

**Из терминала контейнера worker в Dokploy** команды короче: `python scripts/client.py create --wait`, `python scripts/client.py list`. Команды `docker compose ...` выполняются на хосте в каталоге проекта, не внутри контейнера.

## Настроить n8n

1. Откройте n8n, создайте owner account.
2. Создайте credential типа **Header Auth**, назовите **VideoTT API**:
   - Header Name: `Authorization`
   - Header Value: `Bearer ` и затем ваше значение `WORKER_API_KEY` (между Bearer и ключом один пробел).
3. Импортируйте `workflows/manual.json` через **Import from File**.
4. В двух HTTP Request nodes, **Create video** и **Check job**, выберите созданный credential. Экспорт намеренно не содержит секретов или ID вашего credential.
5. В **Choose topic** укажите тему. **Execute workflow** запустит создание; шаг **Record completed video** сохранит UUID и путь скачивания в execution n8n.
6. Для расписания сначала добавьте темы в `/api/v1/topics`, либо выполните `make seed` / в контейнере worker `python scripts/client.py seed`.
7. Импортируйте `workflows/daily.json`, подключите credential в обоих HTTP nodes. В **Daily schedule** по умолчанию один запуск в **10:00 Asia/Almaty**. При желании используйте cron `0 10,18 * * *` для двух или `0 9,14,19 * * *` для трёх запусков в день.
8. Активируйте/опубликуйте **только daily workflow**, когда ручной тест успешен. До этого он выключен.

n8n передаёт только JSON и проверяет статус каждые 30 секунд. MP4 через n8n не проходит. Каждое выполнение использует Idempotency-Key, повтор HTTP-запроса не создаёт второй ролик. Общий предел ожидания — два часа. `FAILED` и `NEEDS_REVIEW` останавливают workflow с понятной ошибкой. `NO_UNUSED_TOPICS` означает, что нужно добавить новые темы; повторять одну тему ежедневно конвейер не будет.

## Скачать все четыре файла одной командой

На компьютере с Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/pip install httpx python-dotenv
# В локальном .env должен быть тот же WORKER_API_KEY, что в Dokploy.
# При SSH-туннеле адрес уже подходит:
.venv/bin/python scripts/client.py download --id VIDEO_UUID --output ./output
# Для домена добавьте --base-url https://video.example.com
```

Получите `output/VIDEO_UUID/` со всеми четырьмя файлами. Не используйте `docker compose exec ... download`, если хотите сохранить файлы именно на своём компьютере: такая команда пишет внутри контейнера.

## Статусы и ошибки

```text
QUEUED → RESEARCHING → SCRIPTING → FETCHING_ASSETS
       → GENERATING_TTS → RENDERING → VALIDATING → READY
                                      ↘ FAILED / NEEDS_REVIEW
```

- **NEEDS_REVIEW:** мало доступных источников, цитата не подтверждена, сценарий не прошёл JSON-проверку или факт-чек. Детали — `error_code`, `evaluation`, `research`, `sources` в API. Никакого обхода проверки кнопкой «всё равно опубликовать» нет.
- **FAILED:** внешний API недоступен, не найден stock, неподходящая длительность озвучки, проблема FFmpeg, заполнен диск или истёк таймаут. Ошибка не содержит ключей.
- **Повтор после исправления:** `POST /api/v1/videos/{id}/render`. Повтор проходит конвейер заново с исследованием и проверкой, а не только FFmpeg; возможны повторные расходы на API. Для READY создавайте новое видео.
- **После рестарта:** runner забирает PostgreSQL advisory lock, возвращает незавершённые задания в очередь и повторяет их до `MAX_JOB_ATTEMPTS`. При потере соединения с блокировкой обработка отменяется; номер попытки защищает БД и финальный каталог от запоздавшего обработчика.
- **Очередь не движется:** проверьте `runner`, его healthcheck и логи. `/health` проверяет API и БД, но не гарантирует доступность внешних сервисов.

## Команды и тесты

```bash
make up           # сборка, миграция, запуск
make down         # остановка без удаления volumes
make logs         # логи worker и runner
make migrate      # явный повтор alembic upgrade head
make seed         # добавить семь стартовых тем, без дублей
make first-video  # создать пример и дождаться результата
make list         # READY videos
make test         # отдельный disposable PostgreSQL, unit/integration tests + smoke
make smoke-test   # offline job + настоящий FFmpeg, без API-ключей и без публикации
```

`make test` использует отдельный `docker-compose.test.yml`, не production БД. После него `docker compose -f docker-compose.test.yml down` остановит тестовый PostgreSQL. `make smoke-test` по умолчанию пишет во временный каталог контейнера; итоговый путь выводится в конце. Для сохранения в volume: `docker compose exec -e SMOKE_OUTPUT_DIR=/data/media/smoke worker python scripts/smoke_test.py`.

Без Docker для разработчика:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r worker/requirements-dev.txt
cd worker
../.venv/bin/pytest -q
../.venv/bin/ruff check app tests migrations
```

PostgreSQL-тесты требуют **отдельную пустую** БД в `TEST_DATABASE_URL`; они пересоздают таблицы. Без неё пропускаются только интеграционные тесты PostgreSQL. FFmpeg smoke требует `ffmpeg` с `libx264`, `aac`, `libass`, `ffprobe` и DejaVu Sans. В Docker это уже установлено. Можно задать `FFMPEG_BIN` / `FFPROBE_BIN` для локального теста.

## Данные и резервные копии

Три named volumes: `postgres_data` (обе БД), `n8n_data` (настройки n8n), `media_data` (видео и исходники). Docker добавит префикс проекта к именам. Перезапуск/Deploy не удаляет данные. **`docker compose down -v` удалит их.**

В `media_data/jobs/{video_id}/attempt-.../` сохраняются исходные клипы, озвучка, word timings и ASS для проверки происхождения/отладки. Промежуточные нормализованные клипы `temp/` удаляются после успешного рендера. Финальная папка публикуется атомарно и доступна через API только после READY. Удаление старых выпусков автоматически не настроено: следите за свободным местом; исходники обычно занимают больше финального MP4.

В Dokploy настройте резервные копии volumes, отдельно сохраните `.env`/Environment и особенно `N8N_ENCRYPTION_KEY`. Для переносимой резервной копии БД из каталога проекта на хосте:

```bash
mkdir -p backups
chmod 700 backups
docker compose exec -T postgres pg_dump -U postgres -d videott -Fc > backups/videott.dump
docker compose exec -T postgres pg_dump -U postgres -d n8n -Fc > backups/n8n.dump
```

Для согласованной копии медиа и БД временно выключите расписание n8n и остановите runner, сделайте дампы/backup `media_data` и `n8n_data`, затем запустите runner. Копии содержат приватные исследования и настройки n8n; храните их вне репозитория. Не меняйте Compose project name без переноса volumes: иначе Docker создаст новые пустые volumes.

## Архитектура и границы MVP

- `postgres`: PostgreSQL 16, две БД и отдельные роли `videott` / `n8n`, без опубликованного порта 5432.
- `migrate`: одноразовый Alembic перед запуском приложения.
- `worker`: FastAPI, постановка заданий и защищённая выдача файлов.
- `runner`: один последовательный consumer persistent queue; тяжёлую работу делает здесь, не в HTTP-запросе.
- `n8n`: расписание, HTTP-команды и журнал завершений.

Исследование требует минимум два домена с реально загруженными текстами. Каждый факт имеет ссылку и цитату, которая должна встречаться в источнике. Модель сценария видит только research context; отдельный проход проверяет сценарий и caption против первичных выдержек. Это разумный фильтр, **не гарантия истинности**: страницы могут повторять одну ошибку, а LLM-проверка тоже может ошибаться. Просмотр перед ручной публикацией остаётся частью процесса.

Другие ограничения: источники за paywall/защитой и PDF не обходятся; stock — иллюстративный видеоряд, не гарантированно точные исторические кадры; crop иногда требует ручной оценки; повтор клипа допустим лишь при отсутствии новых результатов. Текущая озвучка генерируется по сценам, поэтому на стыках возможны паузы. Edge TTS — community package, работающий с онлайн-сервисом Microsoft, без SLA; для устойчивого коммерческого использования можно заменить TTSProvider. Лицензии исходников нужно соблюдать, включая ограничения на использование узнаваемых людей/брендов. Нет музыки, фронтенд-дашборда, автоматической публикации, account management или мониторинга соцсетей.

Синтетический smoke не подтверждает качество настоящей фактологии и релевантность stock. Полный live-тест выполняется после добавления ваших ключей. Проверенные официальные ссылки и детали API: [docs/API_SOURCES.md](docs/API_SOURCES.md). Отчёт о выполненных проверках: [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## Структура

```text
VideoTT/
├── docker-compose.yml
├── docker-compose.test.yml
├── .env.example
├── Makefile
├── IMPLEMENTATION_PLAN.md
├── README.md
├── docs/
├── scripts/                 # env, API CLI, smoke, генератор workflows, init БД
├── workflows/               # manual.json, daily.json
├── worker/
│   ├── Dockerfile
│   ├── requirements*.txt
│   ├── alembic.ini
│   ├── migrations/
│   ├── app/
│   │   ├── main.py          # API и authentication
│   │   ├── runner.py        # persistent consumer + supervisor
│   │   ├── queue.py
│   │   ├── pipeline.py
│   │   ├── config.py
│   │   ├── schemas.py
│   │   ├── db/              # SQLAlchemy
│   │   └── services/        # research, LLM, stock, TTS, subtitles, FFmpeg, output
│   └── tests/
└── .github/workflows/ci.yml
```
