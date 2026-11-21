import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import db, errorlog, jobs, maintenance, serverlog, storage
from app import tts as tts_service
from app.config import insecure_defaults, settings
from app.routers import admin, analytics, auth, billing, books, pages, progress, tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")
serverlog.install()  # the newest log lines, for the /admin page


@asynccontextmanager
async def lifespan(app: FastAPI):
    problems = insecure_defaults(settings)
    if problems and settings.site_domain:  # production: never run with secrets published in the repository
        raise RuntimeError("refusing to start, set in .env: " + ", ".join(problems))
    if problems:
        log.warning("development defaults in use: %s", ", ".join(problems))
    applied = db.migrate()
    if applied:
        log.info("applied migrations: %s", ", ".join(applied))
    storage.ensure_bucket()
    jobs.recover()
    tts_service.start_background()  # cache lifecycle rule + voice preload (non-blocking)
    maintenance.start()  # daily retention purge
    log.info(
        "ready: translator=%s tts=%s billing=%s",
        settings.translator_kind,
        settings.tts_provider,
        "on" if settings.billing_enabled else "off",
    )
    yield
    maintenance.stop()
    db.close_pool()


app = FastAPI(title="LexMatches API", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """FastAPI echoes the submitted values ("input") in 422 responses, which the error log keeps: a password
    in a malformed login would be stored. Only the location and message are returned."""
    errors = [{"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
app.middleware("http")(errorlog.middleware)  # every failed response and unhandled exception -> server_errors

for module in (auth, books, pages, progress, tts, billing, analytics, admin):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    db.fetch_one("SELECT 1 AS ok")
    return {"status": "ok", "translator": settings.translator_kind, "billing": settings.billing_enabled}
