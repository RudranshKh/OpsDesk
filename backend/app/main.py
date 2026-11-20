import asyncio
import logging
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.directory import router as directory_router
from app.api.routes.tickets import router as tickets_router
from app.api.routes.routing import router as routing_router
from app.api.routes.insights import router as insights_router
from app.core.config import settings
from app.core.trusted_proxy import TrustedProxyHeadersMiddleware
from app.db.init import initialize_database
from app.db.session import SessionLocal
from app.services.auth_security import cleanup_expired_auth_records
from app.services.sla import evaluate_open_ticket_slas

logger = logging.getLogger(__name__)


def _run_sla_sweep() -> None:
    with SessionLocal() as db:
        evaluate_open_ticket_slas(db)


def _cleanup_auth_records() -> None:
    with SessionLocal() as db:
        cleanup_expired_auth_records(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate_startup()
    initialize_database()
    _cleanup_auth_records()
    async def sla_worker() -> None:
        while True:
            await asyncio.sleep(settings.sla_poll_seconds)
            try:
                await asyncio.to_thread(_run_sla_sweep)
            except Exception:
                logger.exception("Scheduled SLA evaluation failed")
            if asyncio.get_running_loop().time() - last_auth_cleanup[0] >= 3600:
                try:
                    await asyncio.to_thread(_cleanup_auth_records)
                    last_auth_cleanup[0] = asyncio.get_running_loop().time()
                except Exception:
                    # Avoid logging database URLs or driver details from auth maintenance.
                    logger.error("Scheduled authentication-record cleanup failed")

    last_auth_cleanup = [asyncio.get_running_loop().time()]
    worker = asyncio.create_task(sla_worker(), name="opsdesk-sla-evaluator")
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)
app.add_middleware(
    TrustedProxyHeadersMiddleware,
    trusted_proxy_ips=settings.trusted_proxy_ips,
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path not in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}:
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(directory_router, prefix=settings.api_prefix)
app.include_router(tickets_router, prefix=settings.api_prefix)
app.include_router(routing_router, prefix=settings.api_prefix)
app.include_router(insights_router, prefix=settings.api_prefix)
