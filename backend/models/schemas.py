from pydantic import BaseModel
from typing import Optional


class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    session_id: str
    escalated: bool = False


class WebSocketMessage(BaseModel):
    type: str  # "message" | "typing" | "escalation" | "error"
    content: Optional[str] = None
    session_id: Optional[str] = None
    escalated: Optional[bool] = None
    reason: Optional[str] = None
