"""Журнал событий хоста для админки и автотеста (см. ``app.core.event_log``)."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import require_permission
from app.core import event_log
from app.core.permissions import METRICS_READ

router = APIRouter(
    prefix="/admin/logs",
    tags=["admin-logs"],
    dependencies=[Depends(require_permission(METRICS_READ))],
)


def _since(since: datetime | None, hours: int) -> datetime:
    if since is not None:
        return since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@router.get("/events")
def list_log_events(
    since: datetime | None = None,
    hours: int = Query(default=24, ge=1, le=24 * 31),
    event: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=500, ge=1, le=5000),
) -> Any:
    """Последние события (старые первыми). ``event`` — префикс, например ``support.``."""
    data = event_log.read_events(
        since=_since(since, hours), event_prefix=event, limit=limit
    )
    return {"data": data, "count": len(data)}


@router.get("/summary")
def get_log_summary(
    since: datetime | None = None,
    hours: int = Query(default=24, ge=1, le=24 * 31),
) -> Any:
    """Сводка: HTTP-статусы и задержки, маршруты ответов, движки, ошибки."""
    start = _since(since, hours)
    events = event_log.read_events(since=start, limit=0)
    return {"since": start.isoformat(), **event_log.summarize(events)}


@router.get("/files/{day}")
def download_log_file(day: str) -> FileResponse:
    """Файл журнала за день (UTC) целиком, ``day`` в формате YYYY-MM-DD."""
    try:
        parsed = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
    path = event_log.file_for(parsed)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No log file for this day")
    return FileResponse(path, media_type="application/x-ndjson", filename=path.name)
