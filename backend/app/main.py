import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import settings
from .db import connect, initialize
from .i18n import translate
from .routers import auth, credentials, demo, jobs, keys
from .routers import topology as topology_router
from .security import AppError, bootstrap


@asynccontextmanager
async def lifespan(app):
    initialize()
    bootstrap()
    yield


app = FastAPI(
    title="Tunnel Manager API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
P = "/api/v1"


def language(request):
    return request.headers.get("accept-language", "en")


@app.exception_handler(AppError)
async def app_error(request, exc):
    return JSONResponse(
        {
            "code": exc.code,
            "message": translate(exc.code, language(request)),
            "details": exc.details,
        },
        status_code=exc.status,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {
            "code": "validation_error",
            "message": translate("validation_error", language(request)),
            "fields": [".".join(str(x) for x in e["loc"]) for e in exc.errors()],
        },
        status_code=422,
    )


@app.middleware("http")
async def secure_headers(request, call_next):
    if (
        request.headers.get("content-length", "").isdigit()
        and int(request.headers["content-length"]) > 1_000_000
    ):
        return JSONResponse({"code": "body_too_large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
def health():
    with connect() as db:
        leader = db.execute("SELECT * FROM leader WHERE id=1").fetchone()
        version = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    return {
        "ok": True,
        "schema_version": version,
        "worker_alive": bool(leader and leader["until"] > time.time()),
        "demo": settings.DEMO,
    }


for router in (
    auth.router,
    credentials.router,
    topology_router.router,
    jobs.router,
    keys.router,
):
    app.include_router(router, prefix=P)


app.include_router(demo.router, prefix=P)
