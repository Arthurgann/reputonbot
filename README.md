
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
