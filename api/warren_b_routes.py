"""FastAPI routes for Warren B AI Financial Advisor."""
import logging
import uuid
from typing import Annotated

import requests
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
from ai.warren_b import chat, generate_briefing, generate_monthly_strategy
from api.paper_portfolio import get_recent_warren_decisions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/warren-b", tags=["warren-b"])


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
def warren_chat(req: ChatRequest) -> ChatResponse:
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
def warren_stream(req: ChatRequest) -> StreamingResponse:
    """SSE streaming endpoint for web chat UI."""
    import anthropic as anthropic_sdk
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

    def event_stream():
        client = anthropic_sdk.Anthropic(api_key=config.CLAUDE_API_KEY)
        full_response = []
        try:
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                system=WARREN_B_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"{context}\n\n{req.message}"}],
            ) as stream:
                # Emit session_id as first event so client can correlate
                yield f'data: {{"session_id": "{session_id}"}}\n\n'
                for text in stream.text_stream:
                    full_response.append(text)
                    yield f"data: {text}\n\n"
            yield "data: [DONE]\n\n"
            log_warren_conversation(
                session_id=session_id, interface="web",
                role="warren", content="".join(full_response),
            )
        except Exception as exc:
            logger.exception("Warren B stream failed")
            yield "data: Warren B is temporarily unavailable.\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/briefing", status_code=202)
def trigger_briefing(background_tasks: BackgroundTasks) -> JSONResponse:
    """Trigger Warren B's daily briefing."""
    background_tasks.add_task(_run_briefing_and_post)
    return JSONResponse(status_code=202, content={"status": "accepted", "mode": "warren-briefing"})


@router.post("/monthly", status_code=202)
def trigger_monthly(background_tasks: BackgroundTasks) -> JSONResponse:
    """Trigger Warren B's monthly strategy."""
    background_tasks.add_task(_run_monthly_and_post)
    return JSONResponse(status_code=202, content={"status": "accepted", "mode": "warren-monthly"})


@router.post("/slack-command")
def slack_command(
    text: Annotated[str, Form()] = "",
    user_id: Annotated[str, Form()] = "",
    response_url: Annotated[str, Form()] = "",
) -> JSONResponse:
    """Slack slash command handler for /warren."""
    session_id = f"slack-{user_id}-{uuid.uuid4()}"
    question = text.strip() or "Give me a quick market update."
    try:
        response = chat(message=question, session_id=session_id, interface="slack")
        return JSONResponse(content={"response_type": "in_channel", "text": f"*Warren B*\n\n{response}"})
    except Exception as exc:
        logger.exception("Warren B Slack command failed")
        return JSONResponse(content={"response_type": "ephemeral",
                                     "text": "Warren B is temporarily unavailable. Try again in a moment."})


@router.get("/decisions")
def get_decisions(days: int = 30) -> list:
    """Return Warren B's recent decisions."""
    return get_recent_warren_decisions(days=days)


@router.get("/ui", response_class=HTMLResponse)
def warren_ui() -> HTMLResponse:
    """Serve Warren B web chat interface."""
    from pathlib import Path
    html_path = Path(__file__).parent.parent / "static" / "warren_b_chat.html"
    if not html_path.exists():
        return HTMLResponse("<html><body><h1>Warren B UI not found</h1></body></html>", status_code=404)
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
