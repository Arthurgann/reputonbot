#!/usr/bin/env python3
"""
Простой скрипт для проверки существования маршрута n8n в приложении
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.main import app

# Проверяем, что маршрут для вебхука n8n существует
routes = [route.path for route in app.routes]
if "/webhook/n8n" in routes:
    print("[OK] Маршрут для вебхука n8n существует: /webhook/n8n")
else:
    print("[ERROR] Маршрут для вебхука n8n не найден")

print("\nВсе доступные маршруты:")
for route in app.routes:
    methods = ', '.join(route.methods)
    print(f"  {methods} {route.path}")