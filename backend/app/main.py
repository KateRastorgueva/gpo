import re
import uuid

import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core import event_log
from app.core.config import settings


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
# Частые служебные запросы не засоряют журнал.
_SKIP_PATHS = {f"{settings.API_V1_STR}/utils/health-check/"}


@app.middleware("http")
async def log_http_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Одно событие ``http.request`` на каждый запрос к API (без тела и токенов)."""

    path = request.url.path
    if not path.startswith(settings.API_V1_STR) or path in _SKIP_PATHS:
        return await call_next(request)
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    timer = event_log.Timer()
    status = 500
    try:
        response: Response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        event_log.log_event(
            "http.error",
            request_id=request_id,
            method=request.method,
            path=path,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        route = request.scope.get("route")
        event_log.log_event(
            "http.request",
            request_id=request_id,
            method=request.method,
            route=getattr(route, "path", None) or _UUID_RE.sub("{id}", path),
            status=status,
            duration_ms=timer.ms(),
            content_length=request.headers.get("content-length"),
            authorized="authorization" in request.headers,
            user_agent=request.headers.get("user-agent", "")[:120] or None,
        )


# Каждый воркер при старте чистит журнал старше срока хранения и отмечается в нём.
event_log.cleanup_old_files()
event_log.log_event("app.startup", rag_provider_env=settings.RAG_PROVIDER)


app.include_router(api_router, prefix=settings.API_V1_STR)
