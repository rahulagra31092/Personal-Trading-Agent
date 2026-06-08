import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse

from data.cache import init_db
from api.analyze import router as analyze_router
from api.portfolio import router as portfolio_router
from api.warren_b_routes import router as warren_b_router
from api.health import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Trading Analyst API", version="1.0.0", lifespan=lifespan)
app.include_router(analyze_router)
app.include_router(portfolio_router)
app.include_router(warren_b_router)
app.include_router(health_router)


def _run_daily() -> None:
    from api.briefing import send_daily_briefing
    try:
        send_daily_briefing()
    except Exception:
        logger.exception("Daily briefing failed")


def _run_monthly() -> None:
    from api.briefing import send_monthly_briefing
    try:
        send_monthly_briefing()
    except Exception:
        logger.exception("Monthly briefing failed")


@app.post("/run-briefing/daily", status_code=202)
def trigger_daily_briefing(background_tasks: BackgroundTasks) -> JSONResponse:
    """Kick off the daily briefing in the background. Returns 202 immediately."""
    background_tasks.add_task(_run_daily)
    return JSONResponse(status_code=202, content={"status": "accepted", "mode": "daily"})


@app.post("/run-briefing/monthly", status_code=202)
def trigger_monthly_briefing(background_tasks: BackgroundTasks) -> JSONResponse:
    """Kick off the monthly briefing in the background. Returns 202 immediately."""
    background_tasks.add_task(_run_monthly)
    return JSONResponse(status_code=202, content={"status": "accepted", "mode": "monthly"})
