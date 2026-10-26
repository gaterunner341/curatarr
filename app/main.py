"""Curatarr application entry point."""
import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import api, config, db, scheduler

logging.basicConfig(level=config.LOG_LEVEL,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("curatarr")

STATIC_DIR = Path(__file__).parent / "static"
OPEN_PATHS = {"/api/health"}


def seed_from_yaml() -> None:
    """Import collections.yml from the config folder, adding names that don't exist yet."""
    if config.SEED_FILE.is_file():
        result = api.import_yaml(config.SEED_FILE.read_text(encoding="utf-8"), overwrite=False)
        log.info("Seeded from %s: %s", config.SEED_FILE, result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    try:
        seed_from_yaml()
    except ValueError as exc:
        log.error("Could not read %s: %s", config.SEED_FILE, exc)
    scheduler.start()
    log.info("Curatarr %s started (config: %s)", config.VERSION, config.CONFIG_DIR)
    yield
    scheduler.shutdown()
    db.close()


app = FastAPI(title=config.APP_NAME, version=config.VERSION, lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)


def _authorized(request: Request) -> bool:
    if config.API_KEY:
        supplied = request.headers.get("x-api-key") or request.query_params.get("apikey")
        if supplied and secrets.compare_digest(supplied, config.API_KEY):
            return True
    if config.AUTH_USERNAME and config.AUTH_PASSWORD:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                user, _, password = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                return False
            return (secrets.compare_digest(user, config.AUTH_USERNAME)
                    and secrets.compare_digest(password, config.AUTH_PASSWORD))
        return False
    # With only an API key configured, the UI stays open but the API needs the key.
    return not (config.API_KEY and request.url.path.startswith("/api/"))


@app.middleware("http")
async def auth(request: Request, call_next):
    protected = config.API_KEY or (config.AUTH_USERNAME and config.AUTH_PASSWORD)
    if protected and request.url.path not in OPEN_PATHS and not _authorized(request):
        headers = {}
        if config.AUTH_USERNAME:
            headers["WWW-Authenticate"] = 'Basic realm="Curatarr"'
        return Response("Unauthorized", status_code=401, headers=headers)
    return await call_next(request)


app.include_router(api.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        return Response(status_code=404)
    return FileResponse(STATIC_DIR / "index.html")


def run() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT, log_level=config.LOG_LEVEL.lower(),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    run()
