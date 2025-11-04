# 🔒 ReputonBot — Security P2 (Production Hardening)

## ✅ Фаза A — RLS активация (03.11.2025)

**Цель:** включить прод-защиту и отделить service-доступ от клиентского.

---

### Выполнено

- ✅ Включён **RLS** на всех таблицах:
  - `platform_rules`
  - `interactions`
  - `chat_state`
  - `rate_limits`
  - `request_cache`
- ✅ Добавлена единственная политика (чтение правил площадок):
  ```sql
  CREATE POLICY pr_select ON platform_rules
  FOR SELECT USING (true);```
  
- ✅ Backend использует SUPABASE_SERVICE_ROLE_KEY (подтверждено Kilo Code).

- ✅ Telegram-бот и все endpoints /state/set, /compose_from_state работают стабильно.

- ✅ Supabase REST через anon:
  /rest/v1/chat_state → 401/403 (закрыто)
  /rest/v1/platform_rules → 200 (SELECT разрешён)

 ### 🧪 SMOKE-проверки

| Endpoint | Ожидаемый результат | Статус |
|-----------|--------------------|--------|
| `/healthz` | 200 OK | ✅ |
| `/readyz` | 200 OK | ✅ |
| `/state/set` | 200 OK | ✅ |
| `/compose_from_state` | 200 OK / 429 при лимите | ✅ |
| REST `/chat_state` (anon) | 401 / 403 (доступ закрыт) | ✅ |
| REST `/platform_rules` (anon) | 200 (SELECT доступен) | ✅ |

 Вывод
 -Backend работает под service-role, не затронут RLS.
 -Все клиентские ключи (anon) не имеют доступа к данным.
 -Производительность не изменилась.
 -Защита уровня production включена успешно.
 -Telegram-бот функционирует штатно.

🔜 Фаза B (на будущее)
 -Добавить JWT-проверку (verify_token() в FastAPI + anon key).
 -Ввести политику доступа по chat_id для аутентифицированных пользователей.
 -Настроить напоминание о ротации ключей (OPENAI_API_KEY, SUPABASE_SERVICE_ROLE_KEY, TELEGRAM_TOKEN) —  через n8n cron каждые 30 дней.


