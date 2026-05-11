import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent.db.engine import init_db
from agent.ingest.routes import router as ingest_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Property Maintenance Triage Agent", lifespan=lifespan)
app.include_router(ingest_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
