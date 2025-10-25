from typing import Dict, List
import httpx
import json
from ..config import settings

# Global HTTP client for OpenAI with keep-alive and HTTP/2
_openai_client: httpx.AsyncClient = None

async def get_openai_client() -> httpx.AsyncClient:
    """Get or create persistent OpenAI HTTP client"""
    global _openai_client
    if _openai_client is None or _openai_client.is_closed:
        _openai_client = httpx.AsyncClient(
            http2=True,  # Enable HTTP/2
            timeout=httpx.Timeout(10.0, connect=3.0, read=7.0),  # Optimized timeouts: connect 3s, read 7s
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0),
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
        )
    return _openai_client

async def compose_text_async(
    system_prompt: str,
    user_text: str,
    business_type: str | None,
    platform_name: str | None = None,
    rules: dict | None = None,
    instruction_template: str | None = None,
    tips: list | None = None,
    report_url: str | None = None
) -> Dict:
    # Prepare the full prompt with platform context
    rules_text = "\n".join([f"{k}. {v}" for k, v in rules.items()]) if isinstance(rules, dict) else str(rules or 'Правила не указаны')
    
    tips_text = "\n".join([f"- {tip}" for tip in tips]) if isinstance(tips, list) else str(tips or '')
    
    full_prompt = f"""{system_prompt}

Платформа: {platform_name or 'не указана'}
Текст отзыва: {user_text}
Тип бизнеса: {business_type or 'не указан'}

Правила площадки:
{rules_text}

Шаблон инструкции:
{instruction_template or 'Шаблон не указан'}

Советы:
{tips_text}

URL для жалоб: {report_url or 'URL не указан'}

Верни JSON с ключами: complaint, instruction, tips[], probability_label. Только JSON.
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
        client = await get_openai_client()
        r = await client.post("https://api.openai.com/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]

        # Try to parse the JSON response
        parsed_result = json.loads(content)

        # Validate that required keys are present
        required_keys = ["complaint", "instruction", "tips"]
        for key in required_keys:
            if key not in parsed_result:
                raise ValueError(f"Missing required key '{key}' in LLM response")

        return parsed_result
    except json.JSONDecodeError:
        # Fallback when LLM returns invalid JSON
        print(f"LLM returned invalid JSON: {content}")
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
        return {"complaint": complaint, "instruction": instruction, "tips": tips, "probability_label": "Низкая"}
    except ValueError as e:
        # Fallback when LLM response is missing required keys
        print(f"LLM response missing required keys: {e}")
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
        return {"complaint": complaint, "instruction": instruction, "tips": tips, "probability_label": "Низкая"}
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
        return {"complaint": complaint, "instruction": instruction, "tips": tips, "probability_label": "Низкая"}
