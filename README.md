
# ReputonBot Backend

Backend for the ReputonBot - a Telegram bot that helps users compose complaints against reviews on various platforms.

## API Endpoints

- `POST /compose` - Main endpoint for complaint composition
- `POST /webhook/n8n` - Webhook for n8n integration
- `GET /health` - Health check endpoint
- `POST /state/set` - Save chat state with selected platform
- `POST /compose_from_state` - Compose response based on platform stored in chat state
- `GET /healthz` - Detailed health check endpoint with database connectivity
- `GET /readyz` - Readiness check endpoint

### Health Check Endpoints

#### `/healthz`
Detailed health check that verifies application and database status.

**Successful response:**
```json
{
 "status": "ok",
  "version": "0.1.0",
  "uptime_s": 123,
  "db": "ok"
}
```

**Failed response (HTTP 503):**
```json
{
  "status": "down",
  "version": "0.1.0",
  "uptime_s": 123,
  "db": "down"
}
```

#### `/readyz`
Readiness check that verifies application is ready to serve requests.

**Successful response:**
```json
{
  "ready": true,
  "version": "0.1.0"
}
```

**Failed response (HTTP 503):**
```json
{
  "ready": false,
 "version": "0.1.0"
}
```

## Environment Variables

- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` - Supabase service role key
- `OPENAI_API_KEY` - OpenAI API key

## Running the Application

1. Install dependencies: `pip install -r requirements.txt`
2. Set up environment variables
3. Run the application: `uvicorn backend.main:app --reload`

## Database Setup

**Схема БД: v0.1.1 (schema sync)**

The application uses Supabase as its database. The schema is defined in `supabase_bootstrap.sql`.

### Таблицы

**interactions**: id, tg_user_id, platform, input_text, output_json, created_at, chat_id, request_id (NULL), meta_json (NULL)

**rate_limits**: chat_id, utc_day, hits, threshold (без переименований в этом релизе)

**request_cache**: chat_id, text_hash, platform, response, status, created_at (без поля expires_at)

**chat_state**: chat_id, platform, updated_at

**platform_rules**: id, platform, system_prompt, rules, report_url, created_at

### 🔧 Рекомендуемые поля и индексы (актуально, v0.1.1)

#### interactions
- Индекс: `interactions_user_time_idx` на (tg_user_id, created_at DESC) — история по пользователю быстро
- Частичный UNIQUE: `interactions_request_id_uq_partial` (WHERE request_id IS NOT NULL) — идемпотентность платёжных/вебхук-запросов
- Опционально: `interactions_meta_json_gin` — аналитические фильтры по метаданным

> Примечание: в коде используется `tg_user_id`; в старой документации встречается `telegram_id` — считаем это одним и тем же полем.

#### chat_state
- Индекс: `chat_state_updated_at_idx` на `updated_at DESC` — уже создан, используется для TTL проверок

#### rate_limits
- Индексы: `rate_limits_created_at_idx` (на created_at — уже создан), `rate_limits_chat_id_idx` (частые чтения пользователю)
- Примечание: поле `updated_at` отсутствует — это ок; можно добавить в будущем для служебных задач

#### request_cache
- Индекс: `request_cache_chat_id_text_hash_platform` на `(chat_id, text_hash, platform)` — для быстрого поиска по содержимому
- Примечание: поле `expires_at` отсутствует — TTL можно добавить в будущем

#### platform_rules
- Рекомендация: индекс на `updated_at` (если есть) или оставить без изменений; GIN по `rules_json` добавлять только при реальном поиске по JSON

### Совместимость и план на будущее

- В этом релизе не переименовываем `hits`→`hits_today`
- `request_id` добавлен в `interactions`, используется для идемпотентности
- Для `rate_limits` и `request_cache` поля `updated_at` / `expires_at` не добавлялись — это будущий апдейт (TL/сервисные сценарии)
- Идемпотентность: `X-Request-ID` → `interactions.request_id`
- Ускорение повторов: кэш по содержимому (`chat_id,text_hash,platform`) → `request_cache`

## New State-Based Flow

The application now supports a new workflow where the platform selection is stored in the database and used for subsequent requests:

1. User selects a platform (e.g., via inline buttons in Telegram bot)
2. Bot calls `POST /state/set` to save the selected platform for the chat
3. User sends complaint text
4. Bot calls `POST /compose_from_state` which retrieves the platform from database and processes the complaint

### New Endpoints Usage

#### `/state/set`
Save platform selection for a chat:
```bash
curl -X POST http://localhost:8000/state/set \
  -H "Content-Type": "application/json" \
  -d '{"chat_id": 11222333, "platform": "ozon"}'
```

#### `/compose_from_state`
Process complaint using stored platform:
```bash
curl -X POST http://localhost:8000/compose_from_state \
  -H "Content-Type": "application/json" \
  -d '{"chat_id": 11222333, "text": "пользовательский текст"}'
```

### Payload Examples

**POST /state/set:**
```json
{
  "chat_id": 11222333,
 "platform": "ozon"
}
```

**POST /compose_from_state:**
```json
{
  "chat_id": 1122233,
  "text": "пользовательский текст"
}
```

## Architecture

The application is built with FastAPI and follows a modular structure:

- `main.py` - Main application with endpoints
- `models/` - Pydantic models
- `services/` - Business logic and database operations
- `routes/` - Additional routes (if any)

## 🔍 Health & Readiness

The backend provides two diagnostic endpoints for deployment and monitoring:

- **GET `/healthz`** — returns the current app and database status.  
  Example:

  ```json
  {"status":"ok","version":"0.1.0","db":"ok","uptime_s":120}

  Fields:
  status — "ok" or "down"
  db — "ok" if Supabase responds, "down" otherwise
  version — value from APP_VERSION in .env
  uptime_s — seconds since application startup

- **GET `/readyz`** — indicates whether the service is ready to handle requests.
  Currently duplicates /healthz, but later may include cache warm-up checks.

Use these endpoints to verify backend availability after deployment or when debugging integration issues with n8n or Supabase.

## Client Expectations (n8n Integration)

- Клиент (n8n) передаёт заголовок `X-Request-ID` в `/state/set` и `/compose_from_state`
  — любой уникальный идентификатор выполнения workflow.
- Клиент обрабатывает статус-коды:
  - **200** — успешный ответ,
  - **409** — не выбрана или устарела платформа,
  - **429** — лимит запросов на сегодня исчерпан.
- При включённом `Include Response Headers and Status` (Full Response)
  доступны заголовки (`X-Elapsed-ms`, `X-DB-ms`, `X-LLM-ms`) для логирования производительности.

## Mini QA (local, v0.1.1)

**Result:** ✅ Passed 3/4 base checks + headers

- `/healthz` → **200**, JSON `{"status":"ok","version":"...","db":"ok"}`
- `/state/set` → **200**, повтор с тем же `X-Request-ID` возвращает **тот же JSON**
- `/state/set (empty platform)` → **400** `{"error":"invalid_input","field":"platform"}`
- `/compose_from_state` (empty text) → **400** `{"error":"invalid_input","field":"text","reason":"empty"}`
- Idempotency `/compose_from_state` (same `X-Request-ID`) → **bit-for-bit same content**, `X-Request-ID` echoed
- **Timing headers** always present: `X-Request-ID`, `X-Elapsed-ms`, `X-DB-ms`, `X-LLM-ms` (0.0 if no DB/LLM)
- **Content cache** (by `(chat_id, text_hash, platform)`) — optional; to be enabled in v0.1.2

> Note: Rate-limit 429 may trigger during tests — use another `chat_id`, change text, or lift threshold temporarily.

## Readiness & Timeouts

- **Global timeout (middleware):** 30s hard-cap → долгие запросы получают **503** `{"error":"busy","message":"service timeout"}`
- **LLM timeout:** 25s (без retry на 429)
- **DB timing (v0.1.1):** мониторинг медленных запросов (warnings при `select > 2000ms`, `write > 3000ms`); суммарное время в заголовке `X-DB-ms`
- **Per-request DB timeouts:** план на v0.1.2 (точечно на горячих функциях)
- **/readyz:** 200 `{"ready":true}` при доступности БД и наличии `platform_rules`; иначе 503 `{"ready":false}`

## n8n integration: headers & logging

В HTTP-ноде, которая вызывает backend:
- Включи **Options → Include Response Headers**.
- После ноды добавь **Set** (или **Function Item**) и запиши:
  - `elapsed_ms = {{$json.headers['x-elapsed-ms']}}`
  - `db_ms      = {{$json.headers['x-db-ms']}}`
  - `llm_ms     = {{$json.headers['x-llm-ms']}}`
  - `request_id = {{$json.headers['x-request-id']}}`

Заголовки отдаются в нижнем регистре (`x-...`), смотри `Output → JSON → headers` у HTTP-ноды.

## Environment

Required:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `OPENAI_API_KEY`

Recommended:
- `APP_ENV` = `dev` | `prod`
- `LOG_LEVEL` = `INFO` (default) | `DEBUG` | `WARNING` | `ERROR`
- `APP_VERSION` = semver, например `0.1.1`
- `LLM_TIMEOUT_S` = `25` (жёсткий таймаут LLM)
- `CONTENT_CACHE_ENABLED` = `0|1` (кэш одинаковых запросов по содержанию)
- `OPENAI_CLIENT_REUSE_ENABLED` = `0|1` (reuse httpx AsyncClient, keep-alive/HTTP2)

Notes:
- В `dev` удобнее ослаблять rate limit, но мы используем один и тот же код; порог регулируется в БД.

## Idempotency

Клиент должен передавать `X-Request-ID` (UUID). Бэкенд:
- при повторном запросе с тем же `X-Request-ID` возвращает **бит-в-бит** тот же JSON без повторных вызовов LLM/БД;
- `interactions.request_id` хранит связь для идемпотентности.

Проверка (пример):
```powershell
$req=[guid]::NewGuid().ToString()
$body=@{ chat_id=123; text="test" } | ConvertTo-Json
iwr http://127.0.0.1:8010/compose_from_state -Method POST -Headers @{ "X-Request-ID"=$req } -ContentType application/json -Body $body | % Content > a.json
iwr http://127.0.0.1:8010/compose_from_state -Method POST -Headers @{ "X-Request-ID"=$req } -ContentType application/json -Body $body | % Content > b.json
fc.exe a.json b.json # различий быть не должно


---

# 3) Заголовки таймингов (диагностика)

Отдельный подзаголовок, чтобы команда и “будущий ты” быстро находили:

```md
## Timing headers

Каждый ответ содержит:
- `X-Request-ID` — отражает входной (или сгенерированный) request id
- `X-Elapsed-ms` — общее время запроса
- `X-DB-ms` — суммарное время операций БД
- `X-LLM-ms` — суммарное время LLM

В `429/409` заголовки тоже возвращаются (обычно `X-LLM-ms=0.0`).

## Error contracts

- **400** `{"error":"invalid_input","field":"platform|text"[,"reason":"empty|too_long","limit":6000]}`
- **409** `{"error":"no_platform"}` или `{"error":"platform_expired"}`
- **429** `{"error":"limit_reached","reset_at":"24 hours|soon"}`  
  (в том числе, если сработал LLM timeout `LLM_TIMEOUT_S`)
- **503** `{"error":"busy","message":"service timeout"}` — глобальный таймаут middleware (30s)

Все ответы содержат диагностические заголовки (см. Timing headers).

## Health & Readiness

- **GET `/healthz`** — пульс + пинг БД (без прогрева кэша).
- **GET `/readyz`** — сервис готов, если:
  1) БД отвечает, **и**
  2) кэш правил платформ прогрет (запрос `get_platform_rules_cached("ozon")` не падает).

На старте `/readyz` может на доли секунды вернуть 503, затем 200.

## Smoke tests

Полные команды в `docs/SMOKE.md`. Кратко:
1) `/healthz` → 200
2) `/state/set` → 200
3) `/compose_from_state` → 200 (первый вызов), 200 (идемпотентный повтор)
4) При превышении дневного лимита → 429 c заголовками таймингов

## Performance flags

- `OPENAI_CLIENT_REUSE_ENABLED=1` — переиспользование HTTP-клиента (keep-alive/HTTP2), экономит ~0.3–0.6s на «холодных» запросах.
- `CONTENT_CACHE_ENABLED=1` — кэширование одинакового `(chat_id, text_hash, platform)`, снижает нагрузку и латентность на повторах.

## Database schema & migrations

Актуальная схема: **v0.1.1**. Миграции хранятся в `sql/001_v0.1.1.sql`.  
Краткая инструкция применения — в `sql/README.md`.

Ключевые индексы:
- `interactions_request_id_uq_partial` (partial unique) — идемпотентность.
- `request_cache (chat_id, text_hash, platform)` — быстрый поиск дублей.
- `chat_state_updated_at_idx` — TTL-проверки выбора платформы.
- `rate_limits: chat_id_idx` — быстрый счётчик на пользователя/день.

## Observability (lite)

Включается одной переменной окружения:

- `LOG_JSON=1` — логгер `reputonbot` пишет строго JSON-события:
  `debug_startup`, `compose_start`, `compose_done`, `rate_limit_hit`, `invalid_input`, `timeout_llm`.

Каждый HTTP-ответ содержит заголовки таймингов:
- `X-Request-ID`, `X-Elapsed-ms`, `X-DB-ms`, `X-LLM-ms`.

### Режим профилирования (с логом в файл)
**PowerShell (Windows):**
```powershell
$env:LOG_JSON="1"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env 2>&1 |
  Tee-Object -FilePath .\uvicorn.log

LOG_JSON=1 uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env 2>&1 | tee ./uvicorn.log
В обычной работе запускайте короче (без логирования в файл):
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --env-file .env

Быстрый бенч в PowerShell

Отправляем 8 запросов и затем разбираем compose_done:
$BASE="http://localhost:8000"; $CHAT=123
curl "$BASE/state/set" -H "X-Request-ID: obs-lite-000" -H "Content-Type: application/json" -d "{""chat_id"":$CHAT,""platform"":""ozon""}" | Out-Null

1..8 | % {
  $rid="obs-lite-$($_)"; $body="{""chat_id"":$CHAT,""text"":""Тест $_""}"
  curl "$BASE/compose_from_state" -H "X-Request-ID: $rid" -H "Content-Type: application/json" -d $body | Out-Null
}

Get-Content .\uvicorn.log |
  Where-Object { $_ -match '"event":\s*"compose_done"' } |
  Set-Content .\compose_done.jsonl

Get-Content .\compose_done.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Select-Object ts, status, elapsed_ms, db_ms, llm_ms, request_id |
  Format-Table -Auto

Оценка:

elapsed_ms — общее время запроса;

db_ms — суммарное время БД в запросе;

llm_ms — время LLM (если был вызов; при кэш-хите может быть ~0).

FAQ

Где берётся uvicorn.log? Создаётся только при запуске с Tee-Object/tee (режим профилирования).

Будет ли он расти в проде? Нет, в обычном запуске файл не пишется. Для профилирования — да, зато его можно удалить.

Нужно ли делать ротацию? Пока нет. Если потребуется — добавим позже (logrotate/size cap).

