🚀 ReputonBot — Deploy Checklist (Beget VPS)

📂 1. Подготовка локального архива
 Внести нужные изменения в код (VS Code → backend/).
 Убедиться, что requirements.txt лежит в backend/requirements.txt.
 (Опционально) Обновить версию в .env:
   
   APP_VERSION=0.1.x

 Создать архив:
   
   backend.zip

Внутри архива должна быть папка backend, а в ней все файлы (main.py, services/, routes/, requirements.txt, и т.д.).
 Загрузить backend.zip на сервер:
   
   /root/reputonbot/upload/

💻 2. Развёртывание на сервере (через терминал Beget)
cd /root/reputonbot

# Остановить контейнер
docker compose down

# Бэкап текущего backend
mv backend "backend.bak-$(date +%F-%H%M)"

# Распаковать новый архив
unzip -q upload/backend.zip -d ./

# Проверить наличие requirements.txt
test -f backend/requirements.txt && echo "OK" || echo "NOPE"

# Запустить заново
docker compose up -d

# Проверить логи
docker compose logs -n 200

🌐 3. Проверка доступности (с PowerShell или терминала)

 curl.exe -I https://bot.ai-arise.store/healthz
 curl.exe    https://bot.ai-arise.store/readyz

Ожидаем:

 HTTP/1.1 200 OK
 {"ready":true}

⏪ 4. Быстрый откат (если что-то пошло не так)

 cd /root/reputonbot
 docker compose down
 rm -rf backend
 mv backend.bak-YYYY-MM-DD-HHMM backend
 docker compose up -d
 docker compose logs -n 100

✅ 5. Быстрый тест в браузере

Открыть: https://bot.ai-arise.store/healthz
 → {"status":"ok"}

Открыть: https://bot.ai-arise.store/readyz
 → {"ready":true}

Если оба дают 200, всё работает.

