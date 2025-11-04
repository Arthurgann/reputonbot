# Telegram Webhook Runbook (ReputonBot)

## Переменные
```bash
export BOT_TOKEN="12345:ABC..."
export PUBLIC_URL="https://your-domain.example"   # с HTTPS, без завершающего /

# 1) Сбросить старый вебхук
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook"

# 2) Установить новый
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${PUBLIC_URL}/webhook" \
  -d "drop_pending_updates=true"

# 3) Проверить статус
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo" | jq .

Ожидаемые признаки «нормы»
 ok: true, pending_update_count не растёт.
 Нет last_error_date / last_error_message.
 На сервере в логах видны POST /webhook и ответы 200 OK.

Частые проблемы
 400 — нет HTTPS или неверный DNS.
 Timeout — проверь /readyz и заголовки X-Elapsed-ms.
 429 — слишком частый sendChatAction в n8n → добавь задержку.

Traefik checklist (если он используется)
 Middlewares: rateLimit, compress, retry включены.
 HTTP/2 и HSTS включены.
 /healthz, /readyz, /webhook проброшены на backend.
 Таймауты: forward 30 s, read 60 s.