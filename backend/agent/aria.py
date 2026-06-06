"""
Aria agent — multi-tenant conversation engine.
Sessions are persisted to the database (ChatSession table) so they survive
restarts and enable horizontal scaling. An in-memory LRU cache reduces DB
reads for hot sessions.
"""
import json
import logging
import os
import platform
import ssl
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Optional

import anthropic
import httpx

from backend.config import settings
from backend.agent.prompts import build_system_prompt
from backend.agent.tools import TOOLS, dispatch_tool

logger = logging.getLogger(__name__)

MOCK_MODE     = os.getenv("MOCK_MODE", "0") == "1"
FALLBACK_MODEL = "claude-3-5-sonnet-20241022"

# On Windows, use OS certificate store (handles corporate SSL inspection)
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

# ── In-memory LRU cache (hot sessions only) ───────────────────────────────────
# Max 500 sessions in memory; overflow falls back to DB.
_MAX_CACHE = 500
_CACHE_TTL_MINUTES = 30

class _LRUCache:
    def __init__(self, maxsize: int):
        self._store: OrderedDict[str, tuple[list, datetime]] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[list]:
        if key not in self._store:
            return None
        history, ts = self._store[key]
        if datetime.utcnow() - ts > timedelta(minutes=_CACHE_TTL_MINUTES):
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return history

    def set(self, key: str, history: list) -> None:
        self._store[key] = (history, datetime.utcnow())
        self._store.move_to_end(key)
        if len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

_session_cache: _LRUCache = _LRUCache(_MAX_CACHE)

# clinic_id -> cached system prompt string
_prompts: dict[int, str] = {}


def _session_key(clinic_id: int, session_id: str) -> str:
    return f"{clinic_id}:{session_id}"


def _get_prompt(clinic, db=None) -> str:
    if clinic.id not in _prompts:
        _prompts[clinic.id] = build_system_prompt(clinic, db=db)
    return _prompts[clinic.id]


def invalidate_prompt(clinic_id: int) -> None:
    _prompts.pop(clinic_id, None)


def _load_history(clinic_id: int, session_id: str, db) -> list[dict]:
    """Load history from cache; fall back to DB."""
    key = _session_key(clinic_id, session_id)
    cached = _session_cache.get(key)
    if cached is not None:
        return cached
    if db is not None:
        from backend.db.crud import get_chat_history
        history = get_chat_history(db, clinic_id, session_id)
        if history:
            _session_cache.set(key, history)
        return history
    return []


def _save_history(clinic_id: int, session_id: str, history: list[dict],
                  db, channel: str = "web") -> None:
    """Write to cache and DB."""
    key = _session_key(clinic_id, session_id)
    _session_cache.set(key, history)
    if db is not None:
        from backend.db.crud import save_chat_history
        save_chat_history(db, clinic_id, session_id, history, channel)


def clear_session(clinic_id: int, session_id: str, db=None) -> None:
    key = _session_key(clinic_id, session_id)
    _session_cache.delete(key)
    if db is not None:
        from backend.db.crud import delete_chat_session
        delete_chat_session(db, clinic_id, session_id)


async def chat(
    clinic,
    session_id: str,
    user_message: str,
    channel: str = "web",
    db=None,
) -> tuple[str, bool]:
    """Process a message and return (response_text, is_escalated)."""
    history = _load_history(clinic.id, session_id, db)
    history.append({"role": "user", "content": user_message})

    if MOCK_MODE:
        from backend.agent.mock_responses import mock_chat
        text, is_escalated = mock_chat(history)
        history.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        _save_history(clinic.id, session_id, history, db, channel)
        return text, is_escalated

    system_prompt = _get_prompt(clinic, db=db)
    is_escalated  = False
    total_input   = 0
    total_output  = 0
    model         = settings.model

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
                logger.warning("Model %s failed [%s] — falling back to %s",
                               model, type(api_err).__name__, FALLBACK_MODEL)
                model = FALLBACK_MODEL
                continue
            raise

        total_input  += response.usage.input_tokens
        total_output += response.usage.output_tokens
        assistant_content = [b.model_dump() for b in response.content]
        history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            text = _extract_text(response)
            _log_usage(db, clinic.id, session_id, channel, total_input, total_output)
            _save_history(clinic.id, session_id, history, db, channel)
            return text, is_escalated

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = await dispatch_tool(
                        block.name, block.input,
                        clinic=clinic, db=db,
                        session_id=session_id, channel=channel,
                    )
                except Exception as tool_err:
                    logger.exception("Tool error [%s] name=%s", type(tool_err).__name__, block.name)
                    result = {"error": f"Tool execution failed: {type(tool_err).__name__}"}
                if block.name == "escalate_to_human":
                    is_escalated = True
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
            history.append({"role": "user", "content": tool_results})
            continue

        text = _extract_text(response) or "I'm sorry, something went wrong. Please try again."
        _log_usage(db, clinic.id, session_id, channel, total_input, total_output)
        _save_history(clinic.id, session_id, history, db, channel)
        return text, is_escalated


async def chat_stream(
    clinic,
    session_id: str,
    user_message: str,
    channel: str = "web",
    db=None,
):
    """
    Streaming version of chat(). Async generator yielding:
      ("chunk", text_token)          — partial text as it arrives
      ("done",  (full_text, escalated)) — final result
    """
    history = _load_history(clinic.id, session_id, db)
    history.append({"role": "user", "content": user_message})

    if MOCK_MODE:
        from backend.agent.mock_responses import mock_chat
        text, is_escalated = mock_chat(history)
        history.append({"role": "assistant", "content": [{"type": "text", "text": text}]})
        _save_history(clinic.id, session_id, history, db, channel)
        for word in text.split(" "):
            yield ("chunk", word + " ")
        yield ("done", (text, is_escalated))
        return

    system_prompt = _get_prompt(clinic, db=db)
    is_escalated  = False
    total_input   = 0
    total_output  = 0
    full_text     = ""
    model         = settings.model

    while True:
        try:
            async with _client.messages.stream(
                model=model,
                max_tokens=settings.max_tokens,
                system=system_prompt,
                tools=TOOLS,
                messages=history,
            ) as stream:
                async for chunk in stream.text_stream:
                    full_text += chunk
                    yield ("chunk", chunk)
                response = await stream.get_final_message()
        except (anthropic.NotFoundError, anthropic.BadRequestError):
            if model != FALLBACK_MODEL:
                logger.warning("Model %s failed — falling back to %s", model, FALLBACK_MODEL)
                model = FALLBACK_MODEL
                continue
            raise

        total_input  += response.usage.input_tokens
        total_output += response.usage.output_tokens
        assistant_content = [b.model_dump() for b in response.content]
        history.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            _log_usage(db, clinic.id, session_id, channel, total_input, total_output)
            _save_history(clinic.id, session_id, history, db, channel)
            yield ("done", (full_text, is_escalated))
            return

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = await dispatch_tool(
                        block.name, block.input,
                        clinic=clinic, db=db,
                        session_id=session_id, channel=channel,
                    )
                except Exception as tool_err:
                    logger.exception("Tool error [%s] name=%s", type(tool_err).__name__, block.name)
                    result = {"error": f"Tool execution failed: {type(tool_err).__name__}"}
                if block.name == "escalate_to_human":
                    is_escalated = True
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result),
                })
            history.append({"role": "user", "content": tool_results})
            full_text = ""
            continue

        _log_usage(db, clinic.id, session_id, channel, total_input, total_output)
        _save_history(clinic.id, session_id, history, db, channel)
        yield ("done", (full_text or "I'm sorry, something went wrong. Please try again.", is_escalated))
        return


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
