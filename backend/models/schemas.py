from pydantic import BaseModel, Field
from typing import List, Optional
from pydantic import model_validator

class ComposeRequest(BaseModel):
    platform: str
    text: str
    business_type: Optional[str] = None
    tg_user_id: Optional[str] = Field(alias="chat_id", default=None)

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

class StateSetRequest(BaseModel):
    chat_id: int
    platform: str
    
    @model_validator(mode="after")
    def validate_platform(self):
        self.platform = self.platform.strip()
        return self

class ComposeFromStateRequest(BaseModel):
    chat_id: int
    text: str