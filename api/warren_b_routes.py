"""FastAPI routes for Warren B AI Financial Advisor."""
import hashlib
import hmac
import json
import logging
import sqlite3
import time
import uuid
from typing import Annotated

import anthropic as anthropic_sdk
import requests
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
from ai.warren_b import chat, generate_briefing, generate_monthly_strategy
from api.paper_portfolio import get_recent_warren_decisions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/warren-b", tags=["warren-b"])


def _verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Verify that the request includes a valid API key."""
    if not config.WARREN_B_API_KEY:
        # If no API key is configured, skip auth (development mode)
        return
    if not x_api_key or x_api_key != config.WARREN_B_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _verify_slack_signature(x_slack_signature: str, x_slack_request_timestamp: str, body: bytes) -> None:
    """Verify Slack slash command request signature per Slack docs."""
    if not config.SLACK_SIGNING_SECRET:
        logger.warning("SLACK_SIGNING_SECRET not set; Slack signature verification skipped")
        return
    # Reject requests older than 5 minutes
    req_timestamp = int(x_slack_request_timestamp)
    current_timestamp = int(time.time())
    if abs(current_timestamp - req_timestamp) > 300:
        raise HTTPException(status_code=401, detail="Request timestamp too old")
    # Verify signature: Slack-Request-Timestamp=timestamp&Slack-Request-Body-SHA256=body_hash
    sig_basestring = f"v0:{x_slack_request_timestamp}:{body.decode()}"
    my_signature = "v0=" + hmac.new(
        config.SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(my_signature, x_slack_signature):
        raise HTTPException(status_code=401, detail="Slack signature verification failed")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User's message to Warren B")
    session_id: str | None = None
    interface: str = "web"
    real_portfolio_value: float | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


def _post_warren_to_slack(text: str, prefix: str = "*Warren B*") -> None:
    """Post Warren B's response to the configured Slack webhook."""
    if not config.SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set — skipping Slack post")
        return
    payload = {
        "text": f"{prefix}\n\n{text}",
        "unfurl_links": False,
    }
    try:
        resp = requests.post(config.SLACK_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Slack post failed: %s", exc)


def _run_briefing_and_post() -> None:
    try:
        text = generate_briefing()
        _post_warren_to_slack(text, prefix="*Warren B — Daily Briefing*")
    except Exception:
        logger.exception("Warren B briefing failed")


def _run_monthly_and_post() -> None:
    try:
        text = generate_monthly_strategy()
        _post_warren_to_slack(text, prefix="*Warren B — Monthly Strategy*")
    except Exception:
        logger.exception("Warren B monthly strategy failed")


@router.post("/chat", response_model=ChatResponse)
def warren_chat(req: ChatRequest, _: None = Depends(_verify_api_key)) -> ChatResponse:
    """On-demand conversation with Warren B."""
    session_id = req.session_id or str(uuid.uuid4())
    try:
        response = chat(
            message=req.message,
            session_id=session_id,
            interface=req.interface,
            real_portfolio_value=req.real_portfolio_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Warren B chat failed")
        raise HTTPException(status_code=500, detail="Warren B is temporarily unavailable.")
    return ChatResponse(response=response, session_id=session_id)


@router.post("/stream")
def warren_stream(req: ChatRequest, _: None = Depends(_verify_api_key)) -> StreamingResponse:
    """SSE streaming endpoint for web chat UI."""
    from data.warren_b_memory import build_context_string
    from api.paper_portfolio import log_warren_conversation
    from ai.warren_b import WARREN_B_SYSTEM_PROMPT

    session_id = req.session_id or str(uuid.uuid4())
    context = build_context_string(
        session_id=session_id,
        interface="web",
        user_message=req.message,
        real_portfolio_value=req.real_portfolio_value,
    )
    log_warren_conversation(
        session_id=session_id, interface="web",
        role="user", content=req.message,
    )

    client = anthropic_sdk.Anthropic(api_key=config.CLAUDE_API_KEY)

    def event_stream():
        full_response = []
        try:
            with client.messages.stream(
                model=config.CLAUDE_MODEL_SONNET,
                max_tokens=2000,
                system=WARREN_B_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"{context}\n\n{req.message}"}],
            ) as stream:
                session_id_event = json.dumps({"session_id": session_id})
                yield f"data: {session_id_event}\n\n"
                for text in stream.text_stream:
                    full_response.append(text)
                    # JSON-encode each chunk to preserve newlines in SSE format
                    chunk_event = json.dumps({"content": text})
                    yield f"data: {chunk_event}\n\n"
            yield "data: [DONE]\n\n"
            log_warren_conversation(
                session_id=session_id, interface="web",
                role="warren", content="".join(full_response),
            )
        except Exception as exc:
            logger.exception("Warren B stream failed: %s", exc)
            yield "data: Warren B encountered an error. Please try again.\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/briefing", status_code=202)
def trigger_briefing(background_tasks: BackgroundTasks, _: None = Depends(_verify_api_key)) -> JSONResponse:
    """Trigger Warren B's daily briefing."""
    background_tasks.add_task(_run_briefing_and_post)
    return JSONResponse(status_code=202, content={"status": "accepted", "mode": "warren-briefing"})


@router.post("/monthly", status_code=202)
def trigger_monthly(background_tasks: BackgroundTasks, _: None = Depends(_verify_api_key)) -> JSONResponse:
    """Trigger Warren B's monthly strategy."""
    background_tasks.add_task(_run_monthly_and_post)
    return JSONResponse(status_code=202, content={"status": "accepted", "mode": "warren-monthly"})


@router.post("/slack-command")
async def slack_command(
    request: Request,
    x_slack_signature: Annotated[str | None, Header()] = None,
    x_slack_request_timestamp: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Slack slash command handler for /warren. Verifies Slack signature if configured."""
    # Handle raw Request object with raw body reading for signature verification
    if isinstance(request, Request):
        body = await request.body()
        # Verify Slack signature (if signing secret is configured)
        if config.SLACK_SIGNING_SECRET:
            if not x_slack_signature or not x_slack_request_timestamp:
                raise HTTPException(status_code=401, detail="Missing Slack signature headers")
            try:
                _verify_slack_signature(x_slack_signature, x_slack_request_timestamp, body)
            except HTTPException:
                raise

        # Parse form data from raw body
        try:
            import urllib.parse
            form_data = urllib.parse.parse_qs(body.decode())
            text = form_data.get("text", [""])[0].strip()
            user_id = form_data.get("user_id", [""])[0].strip()
        except Exception as exc:
            logger.exception("Failed to parse Slack form data: %s", exc)
            return JSONResponse(status_code=400, content={"detail": "Invalid form data"})
    else:
        # Request object not available (shouldn't happen in normal operation)
        return JSONResponse(status_code=400, content={"detail": "Invalid request context"})

    question = text.strip() if text else "Give me a quick market update."
    session_id = f"slack-{user_id}-{uuid.uuid4()}"
    try:
        response = chat(message=question, session_id=session_id, interface="slack")
        return JSONResponse(content={"response_type": "in_channel", "text": f"*Warren B*\n\n{response}"})
    except Exception as exc:
        logger.exception("Warren B Slack command failed")
        return JSONResponse(content={"response_type": "ephemeral",
                                     "text": "Warren B is temporarily unavailable. Try again in a moment."})


@router.get("/decisions")
def get_decisions(days: int = 30, _: None = Depends(_verify_api_key)) -> list:
    """Return Warren B's recent decisions."""
    return get_recent_warren_decisions(days=days)


@router.get("/sessions")
def get_sessions(limit: int = 20, _: None = Depends(_verify_api_key)) -> list:
    """List recent conversation sessions."""
    try:
        from api.paper_portfolio import _conn
        with _conn() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """SELECT DISTINCT session_id FROM warren_b_conversations
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("get_sessions failed: %s", exc)
        return []


@router.get("/ui", response_class=HTMLResponse)
def warren_ui() -> HTMLResponse:
    """Serve Warren B web chat interface."""
    from pathlib import Path
    html_path = Path(__file__).parent.parent / "static" / "warren_b_chat.html"
    if not html_path.exists():
        return HTMLResponse("<html><body><h1>Warren B UI not found</h1></body></html>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
