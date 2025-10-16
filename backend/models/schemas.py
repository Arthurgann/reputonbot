from pydantic import BaseModel
from typing import List, Optional

class ComposeIn(BaseModel):
    platform: str
    text: str
    business_type: Optional[str] = None
    tg_user_id: Optional[str] = None

class ComposeOut(BaseModel):
    complaint: str
    instruction: str
    tips: List[str]