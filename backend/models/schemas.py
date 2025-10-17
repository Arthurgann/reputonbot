from pydantic import BaseModel
from typing import List, Optional

class ComposeRequest(BaseModel):
    platform: str
    text: str
    business_type: Optional[str] = None
    tg_user_id: Optional[str] = None

class ComposeResponse(BaseModel):
    complaint: str
    instruction: str
    tips: List[str]
    probability_label: Optional[str] = None
    rules_version: Optional[str] = None
    report_url: Optional[str] = None
    system_prompt: Optional[str] = None
    rules: Optional[dict] = None
    instruction_template: Optional[str] = None