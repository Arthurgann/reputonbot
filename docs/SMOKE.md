# ReputonBot — SMOKE

## Env (must exist)
- APP_ENV
- LOG_LEVEL
- APP_VERSION
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- OPENAI_API_KEY
- (optional) LLM_TIMEOUT_S

## 1) healthz
GET /healthz → 200 JSON: {"status":"ok", "db":"ok", ...}

## 2) state/set
POST /state/set
Body: {"chat_id":7591082023,"platform":"ozon"}
Expect: 200 {"status":"ok",...}

## 3) compose_from_state — A/B
POST /compose_from_state
Body A: {"chat_id":7591082023,"text":"Smoke A"}
Body B: {"chat_id":7591082023,"text":"Smoke B"}
Expect: 200 + JSON с полями complaint/instruction/...
*Возможен 429, если превышен дневной лимит — это тоже корректно.*

## 4) Headers (timings)
В ответах должны быть:
- X-Elapsed-ms (>0)
- X-DB-ms (>=0; >0 когда были DB-операции)
- X-LLM-ms (>=0; =0 при идемпотентности по X-Request-ID)

## Примеры (PowerShell)
$req = [guid]::NewGuid().ToString()
iwr http://127.0.0.1:8010/healthz
iwr http://127.0.0.1:8010/state/set -Method POST -ContentType "application/json" -Body '{"chat_id":7591082023,"platform":"ozon"}'
$body = @{ chat_id=7591082023; text="Smoke A" } | ConvertTo-Json
iwr http://127.0.0.1:8010/compose_from_state -Method POST -ContentType "application/json" -Headers @{ "X-Request-ID"=$req } -Body $body
iwr http://127.0.0.1:8010/compose_from_state -Method POST -ContentType "application/json" -Headers @{ "X-Request-ID"=$req } -Body $body