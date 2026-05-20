"""
Aria agent — multi-tenant conversation engine.
Sessions are keyed by (clinic_id, session_id).
Usage is logged to the DB after every API call.
"""
import json
import logging
import os
import platform
import ssl
from typing import Optional

import anthropic
import httpx

from backend.config import settings
from backend.agent.prompts import build_system_prompt
from backend.agent.tools import TOOLS, dispatch_tool

logger = logging.getLogger(__name__)

MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"
FALLBACK_MODEL = "claude-3-5-sonnet-20241022"

# On Windows, use OS certificate store (handles corporate SSL inspection)
# On Linux/Mac (production), default SSL works fine
_timeout = httpx.Timeout(60.0, connect=10.0)

if platform.system() == "Windows":
    import truststore
    _ssl_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    _http_client = httpx.AsyncClient(verify=_ssl_ctx, timeout=_timeout)
else:
    _http_client = httpx.AsyncClient(timeout=_timeout)

_client = anthropic.AsyncAnthropic(
    api_key=settings.anthropic_api_key,
    http_client=_http_client,
)

# session_key -> message history
_sessions: dict[str, list[dict]] = {}

# clinic_id -> cached system prompt string
_prompts: dict[int, str] = {}


def _session_key(clinic_id: int, session_id: str) -> str:
    return f"{clinic_id}:{session_id}"


def _get_prompt(clinic) -> str:
    if clinic.id not in _prompts:
        _prompts[clinic.id] = build_system_prompt(clinic)
    return _prompts[clinic.id]


def invalidate_prompt(clinic_id: int) -> None:
    """Call after updating a clinic's config so the prompt is rebuilt."""
    _prompts.pop(clinic_id, None)


def get_or_create_session(clinic_id: int, session_id: str) -> list[dict]:
    key = _session_key(clinic_id, session_id)
    if key not in _sessions:
        _sessions[key] = []
    return _sessions[key]


def clear_session(clinic_id: int, session_id: str) -> None:
    _sessions.pop(_session_key(clinic_id, session_id), None)


async def chat(
    clinic,
    session_id: str,
    user_message: str,
    channel: str = "web",
    db=None,
) -> tuple[str, bool]:
    """
    Process a message and return (response_text, is_escalated).
    Logs token usage to DB if db session is provided.
    """
    history = get_or_create_session(clinic.id, session_id)
    history.append({"role": "user", "content": user_message})

    if MOCK_MODE:
        from backend.agent.mock_responses import mock_chat
        text, is_escalated = mock_chat(history)
        history.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        return text, is_escalated

    system_prompt = _get_prompt(clinic)
    is_escalated = False
    total_input = 0
    total_output = 0
    model = settings.model

    while True:
        try:
            response = await _client.messages.create(
                model=model,
                max_tokens=settings.max_tokens,
                system=system_prompt,
                tools=TOOLS,
                messages=history,
            )
        except (anthropic.NotFoundError, anthropic.BadRequestError) as api_err:
            if model != FALLBACK_MODEL:
                logger.warning(
                    "Model %s failed [%s] — falling back to %s. Error: %s",
                    model, type(api_err).__name__, FALLBACK_MODEL, str(api_err)[:300],
                )
                model = FALLBACK_MODEL
                continue
            raise

        total_input  += response.usage.input_tokens
        total_output += response.usage.output_tokens

        logger.debug("clinic=%s stop=%s tokens=%s/%s",
                     clinic.slug, response.stop_reason,
                     response.usage.input_tokens, response.usage.output_tokens)

        assistant_content = [b.model_dump() for b in response.content]
        history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            text = _extract_text(response)
            _log_usage(db, clinic.id, session_id, channel, total_input, total_output)
            return text, is_escalated

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = await dispatch_tool(block.name, block.input, clinic=clinic)
                except Exception as tool_err:
                    logger.exception("Tool error [%s] name=%s inputs=%s",
                                     type(tool_err).__name__, block.name, block.input)
                    result = {"error": f"Tool execution failed: {type(tool_err).__name__}"}
                if block.name == "escalate_to_human":
                    is_escalated = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
            history.append({"role": "user", "content": tool_results})
            continue

        text = _extract_text(response) or "I'm sorry, something went wrong. Please try again."
        _log_usage(db, clinic.id, session_id, channel, total_input, total_output)
        return text, is_escalated


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def _log_usage(db, clinic_id: int, session_id: str,
               channel: str, input_tokens: int, output_tokens: int) -> None:
    if db is None:
        return
    try:
        from backend.db.crud import log_usage
        log_usage(db, clinic_id, session_id, channel, input_tokens, output_tokens)
    except Exception:
        logger.exception("Failed to log usage")
