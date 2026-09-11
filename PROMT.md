Ты senior backend/DevOps engineer. Нужно спроектировать и реализовать рабочий MVP автоматизированной фабрики коротких вертикальных видео для TikTok.

Работай непосредственно с текущим репозиторием: создавай файлы, код, Docker-конфигурацию, миграции, тесты и документацию. Не ограничивайся рекомендациями или псевдокодом.

Если какое-то архитектурное решение можно разумно принять самостоятельно, принимай его и двигайся дальше. Не задавай вопросы без необходимости.

Перед использованием внешних API проверь их актуальную официальную документацию. Не придумывай endpoint'ы и параметры.

# 1. Цель проекта

Нужно автоматически создавать оригинальные вертикальные ролики длительностью примерно 60-90 секунд:

topic
→ research
→ fact checking
→ original script
→ scene plan
→ licensed stock videos
→ TTS narration
→ animated subtitles
→ FFmpeg render
→ final MP4
→ TikTok Draft Upload

Первоначальная тематика:

Technology / engineering / history of technology.

Примеры тем:

- Why do F and J keys have bumps?
- Why is the Save icon a floppy disk?
- Why are airplane windows rounded?
- Where did the @ symbol come from?
- Why is QWERTY arranged this way?
- Why was USB-A so easy to insert incorrectly?
- How did QR codes originate?

Контент должен быть рассчитан прежде всего на англоязычную аудиторию.

Целевая ориентация:

1080x1920
9:16
30 fps
H.264 + AAC

# 2. Ключевой принцип

Это НЕ сервис репоста чужих роликов.

Запрещено:

- скачивать произвольные ролики YouTube;
- использовать TikTok/Reels/Shorts других пользователей;
- обходить DRM;
- скрейпить защищённый контент;
- использовать материалы с неизвестной лицензией;
- использовать copyrighted music без разрешения.

На первом этапе визуальный контент брать ТОЛЬКО через официальный Pexels API.

В дальнейшем архитектура должна позволить добавить:

- NASA;
- Smithsonian Open Access;
- Wikimedia Commons;
- другие CC0/Public Domain источники.

Но не реализовывай их в MVP, кроме интерфейсов/абстракций, если они действительно нужны.

# 3. Deployment environment

Сервер уже существует.

Используется:

Dokploy
Docker Compose
Ubuntu/Linux

Проект должен нормально разворачиваться как Dokploy Docker Compose project.

Не использовать Docker Swarm Stack.

Не задавать `container_name`.

Persistent data хранить в Docker named volumes.

Секреты только через environment variables.

Не коммитить реальные API keys.

Создай:

.env.example

и опиши все необходимые переменные.

# 4. Архитектура

Нужно реализовать следующие сервисы.

## PostgreSQL

Хранит:

- topics;
- research results;
- scripts;
- videos;
- scenes;
- assets;
- render jobs;
- publication attempts;
- rights metadata.

Используй миграции.

Можно использовать SQLAlchemy + Alembic.

## n8n

Используется ТОЛЬКО как orchestration layer.

n8n не должен заниматься:

- сложным FFmpeg;
- скачиванием больших файлов через binary nodes без необходимости;
- монтажом;
- тяжёлой обработкой медиа.

n8n вызывает worker через HTTP API.

Используй PostgreSQL как backend n8n.

Если разумнее использовать отдельные DB/schema для n8n и приложения, сделай это.

## video-worker

Python 3.12 + FastAPI.

Внутри worker:

- research orchestration;
- LLM interaction;
- Pexels integration;
- Edge TTS;
- subtitle generation;
- FFmpeg;
- media normalization;
- rendering;
- TikTok adapter.

Структура должна быть модульной.

Примерно:

worker/
  app/
    main.py
    config.py
    db/
    models/
    schemas/
    services/
      research/
      llm/
      stock/
      tts/
      subtitles/
      renderer/
      publishing/
    api/
    utils/

Не обязательно буквально соблюдать эту структуру, если предложишь лучше.

# 5. LLM abstraction

Не завязывай бизнес-логику намертво на одну модель.

Сделай интерфейс типа:

LLMProvider

с операциями приблизительно:

research_topic()
generate_script()
generate_scene_plan()
generate_caption()
evaluate_script()

Первоначальный provider может использовать OpenAI API.

Model name должен задаваться через env:

LLM_MODEL=

Никаких model names, размазанных hardcode по коду.

Если API недоступен, должна существовать возможность mock provider для локального тестирования.

# 6. Research и factual accuracy

Это критично.

Нельзя просто попросить LLM придумать фактологический ролик и автоматически его опубликовать.

Pipeline должен выглядеть примерно так:

topic
→ research
→ sources
→ structured facts
→ script
→ validation
→ render

ResearchResult должен содержать:

topic
summary
facts[]
sources[]

Каждый source:

title
url
publisher/domain
retrieved_at

Script generator должен работать на основе research results.

В prompt явно запрети ему добавлять факты, которых нет в research context.

Перед render сделай automated validation:

- script содержит только поддерживаемые facts;
- нет очевидных внутренних противоречий;
- sources существуют;
- script не пустой;
- длина соответствует ориентировочно 60-90 секундам речи.

Если confidence недостаточный:

status = NEEDS_REVIEW

и автоматическая публикация запрещена.

Не нужно создавать сложную научную систему fact-checking. Нужна разумная MVP-защита от очевидных hallucinations.

# 7. Script format

LLM должен возвращать structured JSON, а не свободный текст.

Пример структуры:

{
  "title": "...",
  "hook": "...",
  "narration": "...",
  "estimated_duration": 72,
  "scenes": [
    {
      "order": 1,
      "narration": "...",
      "visual_query": "close up computer keyboard",
      "duration_hint": 5
    }
  ],
  "caption": "...",
  "hashtags": ["technology", "history"]
}

Ориентир:

8-16 visual scenes на ролик.

Один stock clip не должен идти весь ролик.

Hook должен появляться сразу, примерно в первые 1-3 секунды.

Избегать вступлений вида:

"Today we're going to talk about..."

Предпочитать:

"You've probably touched this thousands of times without knowing why it's there."

Но не hardcode конкретную фразу.

# 8. Pexels integration

Использовать официальный Pexels API.

Использовать актуальный video endpoint семейства:

/v1/videos/...

Для каждой сцены выполнять поиск по visual_query.

Предпочитать:

orientation=portrait

Если подходящего portrait результата нет, разрешить landscape с последующим crop.

Нужно выбрать наиболее подходящий video file:

- достаточное разрешение;
- разумный filesize;
- без скачивания 4K, если оно не нужно;
- минимум Full HD, когда возможно.

Не использовать один и тот же asset несколько раз в одном ролике без необходимости.

Каждый используемый asset ОБЯЗАТЕЛЬНО записывать в БД.

Metadata:

provider
provider_asset_id
author
source_url
asset_url
license
downloaded_at
local_path
video_id
scene_id

Также для каждого готового ролика генерировать:

rights_manifest.json

Пример:

{
  "video_id": "...",
  "assets": [
    {
      "provider": "pexels",
      "asset_id": "...",
      "author": "...",
      "source_url": "...",
      "license": "Pexels License"
    }
  ]
}

Это обязательно.

# 9. TTS

Для MVP использовать Python package:

edge-tts

Но TTS должен быть реализован через abstraction:

TTSProvider

Например:

EdgeTTSProvider

Так, чтобы позднее можно было добавить:

AzureSpeechProvider
OpenAITTSProvider

без изменения остального pipeline.

Voice задавать через ENV:

TTS_VOICE=

Language:

en-US

Не привязывать тайминг сцен только к предполагаемой длительности текста.

После генерации audio определить фактическую duration через ffprobe.

# 10. Subtitles

Нужны нормальные animated short-form subtitles.

Не просто огромный SRT снизу.

Сделай генерацию ASS subtitles.

Требования:

- readable on phone;
- safe margins;
- максимум примерно 1-2 строки;
- reasonable words per caption;
- центр/нижняя центральная область;
- не располагать критичный текст у самого нижнего края интерфейса TikTok;
- поддерживать Unicode;
- использовать bundled/open font или системный шрифт с понятной лицензией.

Если edge-tts может предоставить word/sentence timing, используй его.

Если точных word timings нет, реализуй разумное sentence/chunk timing.

Архитектуру сделай так, чтобы позднее можно было добавить word-by-word highlighting.

# 11. FFmpeg render pipeline

FFmpeg установлен внутри worker container.

Pipeline:

download stock clips
→ normalize
→ trim
→ crop/scale
→ concat
→ narration
→ subtitles
→ output validation

Final output:

MP4
1080x1920
30 fps
H.264
AAC

Нужно учитывать:

- разные aspect ratios;
- разные fps;
- разные codecs;
- короткий исходный stock clip;
- слишком длинный clip;
- отсутствие audio в stock clip.

Оригинальный звук stock video по умолчанию отключить.

Основная audio track:

TTS.

На MVP НЕ добавлять музыку автоматически.

Сначала лучше отсутствие музыки, чем проблемы с copyright.

Позже architecture может позволить background audio provider.

Нормализовать narration loudness разумным способом.

Не делать слишком тяжёлый bitrate.

Добавить проверку результата через ffprobe.

Проверять:

width
height
duration
video codec
audio codec

Если render невалидный:

job status = FAILED

# 12. Media storage

На MVP использовать Docker named volume.

Например:

media_data

Структура внутри:

/data/media/
  jobs/
    {video_id}/
      audio/
      assets/
      temp/
      final/
      rights_manifest.json

Temporary files очищать после успешного render, если они больше не нужны.

Final MP4 и rights manifest сохранять.

Не прокачивать большие media binaries через n8n.

# 13. Job system

Не держать HTTP request открытым 1-2 минуты на render.

Нужно реализовать нормальную asynchronous job model.

Например:

POST /api/v1/videos

возвращает:

{
  "job_id": "...",
  "status": "QUEUED"
}

Затем:

GET /api/v1/jobs/{job_id}

возвращает статус.

Статусы приблизительно:

QUEUED
RESEARCHING
SCRIPTING
FETCHING_ASSETS
GENERATING_TTS
RENDERING
VALIDATING
READY
NEEDS_REVIEW
UPLOADING
UPLOADED
PUBLISHED
FAILED

Background processing можно сделать просто и надёжно.

Для MVP не обязательно сразу добавлять Celery/Redis, если PostgreSQL job queue достаточно.

Но решение должно нормально переживать рестарт worker.

In-memory queue, которая теряет job при рестарте, не подходит.

# 14. API worker

Минимальный API:

GET /health

POST /api/v1/topics
GET /api/v1/topics

POST /api/v1/videos
GET /api/v1/videos/{id}

GET /api/v1/jobs/{id}

POST /api/v1/videos/{id}/render

POST /api/v1/videos/{id}/tiktok/upload

GET /api/v1/videos/{id}/manifest

API naming можешь улучшить.

Добавь OpenAPI через FastAPI.

# 15. TikTok

Использовать ТОЛЬКО официальный TikTok Content Posting API.

Не использовать:

Selenium
Playwright
browser automation
private API
mobile emulator
cookie scraping

MVP:

TikTok Upload API
→ upload video as DRAFT
→ пользователь вручную проверяет его в TikTok и нажимает publish.

Нужно реализовать TikTok publisher как отдельный adapter.

TikTokPublishingProvider

Методы приблизительно:

initialize_upload()
upload_video()
check_status()

OAuth/token lifecycle держать отдельно.

Secrets:

TIKTOK_CLIENT_KEY
TIKTOK_CLIENT_SECRET

Tokens не логировать.

Если полноценный OAuth flow требует callback endpoint, реализуй минимальный безопасный flow либо чётко подготовь backend endpoints для него.

Не симулируй наличие approval TikTok API.

Если отсутствует approved video.upload scope, приложение должно корректно сообщать:

TIKTOK_NOT_CONFIGURED

а остальной pipeline продолжает работать.

То есть TikTok не должен блокировать создание видео.

Direct Post `video.publish` сейчас НЕ является обязательной частью MVP.

Но сделай интерфейс так, чтобы его можно было добавить позже.

# 16. n8n

Создай экспортируемый n8n workflow JSON либо пошагово генерируемый workflow, который можно импортировать.

Workflow MVP:

Schedule Trigger
→ request new video creation
→ poll job status
→ if READY
→ TikTok draft upload
→ log result

Добавь также manual trigger workflow для тестирования.

Важно:

первые тесты должны позволять остановиться на READY и НЕ отправлять TikTok.

Добавь параметр:

AUTO_UPLOAD_TIKTOK=false

Если false:

pipeline заканчивается READY.

# 17. Scheduling

На MVP:

1-3 ролика в сутки.

Не делать aggressive posting.

Schedule должен задаваться через n8n.

Не hardcode расписание внутри worker.

# 18. Database

Продумай нормальную минимальную schema.

Как минимум:

topics
research_results
research_sources
videos
scenes
assets
jobs
publications

Используй UUID.

created_at
updated_at

должны быть timezone aware.

Для ошибок сохранять:

error_code
error_message

Но не secrets.

# 19. Reliability

Все внешние API должны иметь:

timeout
retry
exponential backoff

Но не делать бесконечные retries.

Downloads проверять:

HTTP status
Content-Type
filesize

Добавить ограничения:

MAX_ASSET_SIZE_MB
MAX_VIDEO_DURATION_SEC
MAX_DOWNLOAD_RETRIES

FFmpeg запускать через subprocess безопасно, без shell=True с пользовательским вводом.

Любой LLM JSON валидировать через Pydantic.

# 20. Logging

Structured logging.

Каждый log должен по возможности содержать:

job_id
video_id
stage

Не логировать:

API keys
OAuth tokens
full secrets.

# 21. Security

Worker не должен быть публично открыт без необходимости.

Если n8n обращается к нему внутри Docker network, используй internal hostname.

Если API всё-таки доступен извне, предусмотри API token authentication.

PostgreSQL наружу не публиковать.

Не прописывать:

ports:
  - "5432:5432"

если это не нужно.

# 22. Docker Compose

Создай production-oriented:

docker-compose.yml

Сервисы приблизительно:

postgres
n8n
worker

Можно добавить отдельный worker process/service, если архитектурно это оправдано.

Использовать:

restart: unless-stopped
healthchecks
named volumes
internal networking

Никаких real secrets в compose.

Документировать настройку domain для n8n через Dokploy Domains UI.

Сам worker наружу можно не публиковать.

# 23. Local development

Создай возможность запуска:

docker compose up --build

Для разработки должно быть возможно:

- отключить TikTok;
- использовать mock LLM;
- сгенерировать тестовый ролик;
- протестировать FFmpeg pipeline.

Создай sample topic.

Например:

"Why do the F and J keys on keyboards have raised bumps?"

# 24. Tests

Не нужно 100% coverage.

Но нужны meaningful tests:

- Pydantic script parsing;
- rights manifest generation;
- Pexels response parsing;
- job state transitions;
- render metadata validation;
- TikTok adapter mocked tests.

Добавь smoke test.

Например:

make smoke-test

или:

python scripts/smoke_test.py

Smoke test должен создать тестовый job без реальной публикации в TikTok.

# 25. Developer experience

Добавь:

README.md
.env.example
Makefile

Команды примерно:

make up
make down
make logs
make migrate
make test
make smoke-test

Если Makefile не оправдан, предложи эквивалент.

README должен содержать точные инструкции:

1. clone;
2. configure env;
3. obtain Pexels API key;
4. configure LLM API;
5. docker compose up;
6. migrations;
7. open n8n;
8. import workflow;
9. create first video;
10. configure TikTok later.

# 26. Environment variables

Минимально ожидаю что-то типа:

POSTGRES_PASSWORD=
DATABASE_URL=

N8N_HOST=
N8N_ENCRYPTION_KEY=

PEXELS_API_KEY=

LLM_PROVIDER=
LLM_API_KEY=
LLM_MODEL=

TTS_PROVIDER=edge
TTS_VOICE=

MEDIA_ROOT=/data/media

AUTO_UPLOAD_TIKTOK=false

TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=

WORKER_API_KEY=

Конкретный набор можешь улучшить.

# 27. MVP priorities

Очень важно: не переусложняй.

Приоритеты:

P0:
Docker Compose
Postgres
worker
job persistence
Pexels
TTS
FFmpeg
subtitles
final MP4

P1:
LLM script/scenes
research/source storage
rights manifest
validation

P2:
n8n workflow

P3:
TikTok Draft Upload

Не реализовывай сейчас:

multi-account TikTok
automatic account creation
YouTube downloading
Instagram
YouTube Shorts publishing
analytics feedback loop
NASA
Wikimedia
Smithsonian
AI-generated video
music generation
complex frontend/dashboard
Kubernetes

Подготовить интерфейсы можно, но не превращать MVP в framework.

# 28. Definition of Done

Проект считается готовым к MVP, когда на чистой машине можно выполнить:

git clone
cp .env.example .env
docker compose up --build

затем создать topic:

Why do the F and J keys have raised bumps?

и pipeline создаст:

research data
script
scene plan
Pexels assets
TTS audio
subtitles
rights_manifest.json
final.mp4

Final MP4 должен:

- открываться;
- быть 1080x1920;
- содержать narration;
- содержать subtitles;
- иметь несколько визуальных сцен;
- длиться приблизительно 60-90 секунд;
- не содержать чужой copyrighted audio;
- иметь traceable source metadata для использованных assets.

После настройки TikTok Developer credentials должна быть возможность отправить этот файл через официальный TikTok Upload API как draft.

# 29. Порядок твоей работы

Сначала:

1. Осмотри текущий repository.
2. Если он пустой, создай структуру.
3. Создай короткий IMPLEMENTATION_PLAN.md.
4. Затем сразу переходи к реализации.
5. Не останавливайся после плана.
6. После каждого крупного этапа запускай соответствующие тесты.
7. Если обнаруживаешь ошибку, исправляй её прежде чем идти дальше.
8. Не оставляй critical TODO вместо реализации.
9. TODO допустимы только для вещей, требующих внешних credentials/approval.

После завершения:

- покажи итоговую структуру repo;
- перечисли реализованные части;
- покажи команды запуска;
- перечисли ENV variables, которые мне реально нужно заполнить;
- укажи, что именно ещё потребуется сделать вручную в Dokploy;
- отдельно укажи шаги получения и подключения TikTok Developer credentials;
- сообщи известные ограничения MVP.

Начинай реализацию.


UPDATE!
# Publishing / final output

В MVP НЕ реализовывать автоматическую публикацию в TikTok, Instagram, YouTube или другие социальные сети.

Пользователь будет публиковать готовые ролики вручную.

Конвейер считается завершённым после получения полностью готового к публикации ролика.

Для каждого успешно созданного видео необходимо создать отдельную директорию:

/data/media/output/{video_id}/

Она должна содержать:

final.mp4
caption.txt
metadata.json
rights_manifest.json

## final.mp4

Полностью готовый вертикальный ролик:

1080x1920
9:16
30 fps
H.264
AAC

Содержит:

- смонтированный видеоряд;
- TTS narration;
- animated subtitles;
- hook;
- финальный payoff;
- никаких copyrighted audio tracks.

Видео должно быть готово к ручной загрузке в TikTok без дополнительного монтажа.

## caption.txt

Готовое описание для TikTok.

Формат:

основной caption

пустая строка

hashtags

Не генерировать чрезмерное количество hashtags.

Ориентир:

3-6 релевантных hashtags.

## metadata.json

Пример:

{
  "video_id": "...",
  "topic": "...",
  "title": "...",
  "hook": "...",
  "duration": 72.4,
  "language": "en-US",
  "created_at": "...",
  "status": "READY",
  "sources": [
    {
      "title": "...",
      "url": "..."
    }
  ]
}

## rights_manifest.json

Содержит происхождение каждого использованного media asset.

Пример:

{
  "video_id": "...",
  "assets": [
    {
      "scene_id": "...",
      "provider": "pexels",
      "asset_id": "...",
      "author": "...",
      "source_url": "...",
      "license": "Pexels License",
      "downloaded_at": "..."
    }
  ]
}

Unknown-license assets запрещены.

## Video status

Финальный успешный статус:

READY

Pipeline:

TOPIC
→ RESEARCHING
→ SCRIPTING
→ FETCHING_ASSETS
→ GENERATING_TTS
→ RENDERING
→ VALIDATING
→ READY

При проблеме:

FAILED

Если фактология вызывает сомнения:

NEEDS_REVIEW

## n8n workflow

Основной workflow:

Schedule Trigger
→ request new video
→ poll processing status
→ if READY
→ record completed video
→ finish

Никаких TikTok API calls.

Также сделать Manual Trigger для создания тестового видео по заданной теме.

## Output access

Нужно предусмотреть удобный способ получить готовые ролики.

В MVP реализуй один из двух вариантов, выбрав наиболее простой и безопасный:

A. небольшой authenticated HTTP endpoint для списка READY videos и скачивания final.mp4;

или

B. понятную директорию output в persistent Docker volume.

Предпочтительно реализовать простой web/API endpoint:

GET /api/v1/videos?status=READY
GET /api/v1/videos/{id}
GET /api/v1/videos/{id}/download
GET /api/v1/videos/{id}/caption

Не делать полноценный frontend/dashboard на этом этапе.

Если download endpoint открыт извне, он обязательно должен быть защищён WORKER_API_KEY или другой простой authentication mechanism.

# Что НЕ реализовывать

Не реализовывать:

TikTok Developer API
TikTok OAuth
TikTok Draft Upload
TikTok Direct Post
Selenium
Playwright
browser automation
Instagram API
YouTube publishing

Главная цель MVP:

полностью автоматически превращать тему в готовый final.mp4, который пользователь вручную проверяет и публикует.