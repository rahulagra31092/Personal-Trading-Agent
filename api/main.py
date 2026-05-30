from contextlib import asynccontextmanager
from fastapi import FastAPI
from data.cache import init_db
from api.analyze import router as analyze_router
from api.portfolio import router as portfolio_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Trading Analyst API", version="1.0.0", lifespan=lifespan)
app.include_router(analyze_router)
app.include_router(portfolio_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
