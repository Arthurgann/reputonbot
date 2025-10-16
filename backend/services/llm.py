from typing import Dict, List
import httpx
import json
from ..config import settings

def compose_text(system_prompt: str, user_text: str, business_type: str | None, platform_name: str | None = None, rules_text: str | None = None, report_url: str | None = None) -> Dict:
    # Prepare the full prompt with platform context
    full_prompt = f"""
{system_prompt}

Платформа: {platform_name or 'не указана'}
Правила площадки:
{rules_text or 'Правила не указаны'}

URL для жалоб: {report_url or 'URL не указан'}

Бизнес: {business_type or 'не указан'}
Текст жалобы: {user_text}

Верни JSON с ключами: complaint, instruction, tips[]. Только JSON.
"""

    # Prepare the messages for the OpenAI API
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": full_prompt}
    ]
    
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "gpt-4.1-mini", # Using gpt-4.1-mini as requested
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.7
    }
    
    try:
        with httpx.Client(timeout=60) as client:
            r = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        # Fallback to static response in case of API failure
        print(f"OpenAI API error: {e}")
        complaint = (
            "Прошу проверить данный отзыв на соответствие правилам площадки и удалить/исправить "
            "при наличии нарушений. В тексте содержатся оскорбления и отсутствует подтверждение фактов."
        )
        instruction = (
            "Зайдите в раздел отзывов → 'Пожаловаться' → выберите причину по правилам площадки → "
            "кратко опишите нарушение → приложите подтверждения (номер заказа, чек, скриншоты) → отправьте."
        )
        tips: List[str] = [
            "Держите тон нейтральным, без эмоциональных оценок.",
            "Указывайте конкретику: дата, номер заказа/диалога, товары.",
            "Прикладывайте доказательства — это ускорит рассмотрение."
        ]
        return {"complaint": complaint, "instruction": instruction, "tips": tips}
