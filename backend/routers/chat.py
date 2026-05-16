import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.agent import aria
from backend.db.database import get_db
from backend.db.crud import get_clinic
from backend.models.schemas import ChatMessage, ChatResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _greeting(clinic) -> str:
    return (
        f"Hi there! I'm {clinic.agent_name}, the virtual front desk for {clinic.name}. "
        "How can I help you today? I can schedule appointments, answer insurance questions, "
        "help with billing, or answer any questions about our office."
    )


@router.websocket("/ws/{clinic_slug}/{session_id}")
async def websocket_chat(websocket: WebSocket, clinic_slug: str, session_id: str,
                         db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    logger.info("WS connected: clinic=%s session=%s", clinic_slug, session_id)

    await websocket.send_json({
        "type": "message",
        "content": _greeting(clinic),
        "session_id": session_id,
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                user_message = payload.get("message", "").strip()
            except (json.JSONDecodeError, AttributeError):
                user_message = data.strip()

            if not user_message:
                continue

            await websocket.send_json({"type": "typing", "active": True})

            try:
                response_text, is_escalated = await aria.chat(
                    clinic, session_id, user_message, channel="web", db=db
                )
            except Exception:
                logger.exception("Agent error: clinic=%s session=%s", clinic_slug, session_id)
                await websocket.send_json({"type": "typing", "active": False})
                await websocket.send_json({
                    "type": "error",
                    "content": f"I'm sorry, I ran into a technical issue. Please try again or call us at {clinic.phone}.",
                })
                continue

            await websocket.send_json({"type": "typing", "active": False})
            await websocket.send_json({
                "type": "message",
                "content": response_text,
                "session_id": session_id,
                "escalated": is_escalated,
            })

    except WebSocketDisconnect:
        logger.info("WS disconnected: clinic=%s session=%s", clinic_slug, session_id)
        aria.clear_session(clinic.id, session_id)


@router.post("/api/{clinic_slug}/chat", response_model=ChatResponse)
async def rest_chat(clinic_slug: str, body: ChatMessage, db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        return JSONResponse(status_code=404, content={"error": "Clinic not found."})

    session_id = body.session_id or str(uuid.uuid4())
    try:
        response_text, is_escalated = await aria.chat(
            clinic, session_id, body.message, channel="web", db=db
        )
        return ChatResponse(content=response_text, session_id=session_id, escalated=is_escalated)
    except Exception:
        logger.exception("REST chat error: clinic=%s", clinic_slug)
        return JSONResponse(status_code=500, content={"error": "Internal error. Please try again."})


@router.get("/api/{clinic_slug}/config")
async def clinic_config(clinic_slug: str, db: Session = Depends(get_db)):
    clinic = get_clinic(db, clinic_slug)
    if not clinic:
        return JSONResponse(status_code=404, content={"error": "Clinic not found."})
    return {
        "agent_name":  clinic.agent_name,
        "clinic_name": clinic.name,
        "specialty":   clinic.specialty,
        "phone":       clinic.phone,
    }


@router.get("/api/health")
async def health():
    return {"status": "ok", "service": "Tabor Synergy Agent"}
