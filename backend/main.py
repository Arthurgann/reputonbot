
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(title="ReputonBot Backend", version="0.1.0")

class ComposeIn(BaseModel):
    platform: str
    business_type: str | None = None
    text: str

class ComposeOut(BaseModel):
    complaint: str
    instruction: str
    tips: List[str]

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/compose", response_model=ComposeOut)
def compose(req: ComposeIn):
    # TODO: replace with real LLM + platform rules (Supabase)
    complaint = (
        "Прошу проверить/удалить данный отзыв как нарушающий правила площадки. "
        "Просьба оценить корректность формулировок, наличие оскорблений, "
        "и приложить подтверждающие материалы."
    )
    instruction = (
        "Откройте раздел отзывов → нажмите «Пожаловаться» → укажите причину "
        "по правилам площадки → приложите чек/скриншоты → отправьте."
    )
    tips = [
        "Сохраняйте нейтральный тон, без эмоций и угроз.",
        "Указывайте номер заказа/диалог, если есть.",
        "Прикладывайте доказательства (скрины, фото, документы).",
    ]
    return ComposeOut(complaint=complaint, instruction=instruction, tips=tips)
