"""FastAPI application: REST API, Vapi webhook and dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import SessionLocal, init_db
from app.errors import ApiError, fail, field_errors, ok
from app.routers import calls, patients, vapi
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")

DASHBOARD_FILE = Path(__file__).parent / "static" / "dashboard.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.seed_data:
        with SessionLocal() as session:
            seed_if_empty(session)
    yield


app = FastAPI(title="Patient Registration Voice Agent", lifespan=lifespan)
app.include_router(patients.router)
app.include_router(calls.router)
app.include_router(vapi.router)


@app.exception_handler(ApiError)
async def handle_api_error(_: Request, exc: ApiError):
    return JSONResponse(fail(exc.code, exc.message, exc.details), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    errors = exc.errors()
    # A body that is not parseable JSON is a malformed request (400), not a semantic one (422).
    if any(err.get("type") == "json_invalid" for err in errors):
        return JSONResponse(fail("bad_request", "Request body is not valid JSON"), status_code=400)
    details = field_errors(errors)
    return JSONResponse(fail("validation_error", "Validation failed", details), status_code=422)


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse(fail("http_error", str(exc.detail)), status_code=exc.status_code)


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception):
    logger.exception("unhandled_error", exc_info=exc)
    return JSONResponse(fail("internal_error", "Internal server error"), status_code=500)


@app.get("/health")
def health():
    return ok({"status": "ok"})


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD_FILE)
