import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, errorlog, jobs, storage
from app import tts as tts_service
from app.config import settings
from app.routers import admin, analytics, auth, billing, books, pages, progress, tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    applied = db.migrate()
    if applied:
        log.info("applied migrations: %s", ", ".join(applied))
    storage.ensure_bucket()
    jobs.recover()
    tts_service.start_background()  # cache lifecycle rule + voice preload (non-blocking)
    log.info(
        "ready: translator=%s tts=%s billing=%s",
        settings.translator_kind,
        settings.tts_provider,
        "on" if settings.billing_enabled else "off",
    )
    yield
    db.close_pool()


app = FastAPI(title="LexMatches API", lifespan=lifespan)
app.middleware("http")(errorlog.middleware)  # every failed response and unhandled exception -> server_errors

for module in (auth, books, pages, progress, tts, billing, analytics, admin):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    db.fetch_one("SELECT 1 AS ok")
    return {"status": "ok", "translator": settings.translator_kind, "billing": settings.billing_enabled}
