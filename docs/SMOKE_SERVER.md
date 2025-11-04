## Server SMOKE (после выката на прод)

Заменить `BASE` на публичный домен/нгрок:

```bash
BASE="https://your-domain.example"

# 1) healthz / readyz
curl -s "${BASE}/healthz" | jq .
curl -s "${BASE}/readyz" | jq .

# 2) state/set
curl -s -X POST "${BASE}/state/set" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: smoke.$(date +%s)" \
  -d '{"chat_id":7591082023,"platform":"ozon"}' | jq .

# 3) compose_from_state
curl -i -s -X POST "${BASE}/compose_from_state" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: smoke.$(date +%s)" \
  -d '{"chat_id":7591082023,"text":"Server smoke"}' | sed -n '1,25p'
```
# Проверь заголовки: X-Elapsed-ms / X-DB-ms / X-LLM-ms
