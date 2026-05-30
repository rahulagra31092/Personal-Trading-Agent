from contextlib import asynccontextmanager
from fastapi import FastAPI
from data.cache import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Trading Analyst API", version="1.0.0", lifespan=lifespan)

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
