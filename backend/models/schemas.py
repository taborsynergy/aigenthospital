from pydantic import BaseModel, Field
from typing import Optional

# A single patient chat turn is short; cap it to block oversized-payload abuse
# and runaway LLM token cost. 4000 chars ≈ comfortably longer than any real message.
MAX_MESSAGE_LEN = 4000
MAX_SESSION_ID_LEN = 200


class ChatMessage(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LEN)
    session_id: Optional[str] = Field(default=None, max_length=MAX_SESSION_ID_LEN)


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
