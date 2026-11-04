"""Журнал событий хоста в формате JSON Lines.

Каждое событие — одна JSON-строка в файле ``<EVENT_LOG_DIR>/events-YYYY-MM-DD.jsonl``
(дата по UTC). Журнал нужен, чтобы по работе командного хоста искать баги,
считать метрики (время ответа, доля эскалаций, ошибки) и делать аналитику.

Backend запускается в нескольких воркерах (``fastapi run --workers 4``), поэтому
файл открывается на дозапись на каждое событие: короткая строка, записанная одним
``write`` в режиме O_APPEND, не перемешивается со строками других процессов, а
ротация по дате не требует общего состояния между воркерами.

Журнал не должен ронять запросы: любая ошибка записи проглатывается.
"""

import json
import logging
import os
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

FILE_PREFIX = "events-"
FILE_SUFFIX = ".jsonl"
MAX_TEXT = 500


def _log_dir() -> Path:
    return Path(settings.EVENT_LOG_DIR)


def file_for(day: datetime) -> Path:
    return _log_dir() / f"{FILE_PREFIX}{day:%Y-%m-%d}{FILE_SUFFIX}"


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + "…"
    return value


def log_event(event: str, **fields: Any) -> None:
    """Пишет одно событие. Значения None отбрасываются, длинные строки режутся."""

    if not settings.EVENT_LOG_ENABLED:
        return
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "ts": now.isoformat(timespec="milliseconds"),
        "event": event,
        "env": settings.ENVIRONMENT,
        "pid": os.getpid(),
    }
    record.update(
        {key: _short(value) for key, value in fields.items() if value is not None}
    )
    try:
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        path = file_for(now)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:  # noqa: BLE001 — журнал не должен ломать обработку запроса
        logger.debug("event log write failed", exc_info=True)


def cleanup_old_files(retention_days: int | None = None) -> int:
    """Удаляет файлы журнала старше срока хранения. Возвращает число удалённых."""

    days = (
        settings.EVENT_LOG_RETENTION_DAYS if retention_days is None else retention_days
    )
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    removed = 0
    try:
        for path in _log_dir().glob(f"{FILE_PREFIX}*{FILE_SUFFIX}"):
            stamp = path.name[len(FILE_PREFIX) : -len(FILE_SUFFIX)]
            try:
                day = datetime.strptime(stamp, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
    except OSError:
        logger.debug("event log cleanup failed", exc_info=True)
    return removed


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def read_events(
    *,
    since: datetime | None = None,
    event_prefix: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Последние ``limit`` событий (старые первыми), начиная с ``since``."""

    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    start_day = (since or datetime.now(timezone.utc) - timedelta(days=1)).date()
    files = sorted(_log_dir().glob(f"{FILE_PREFIX}*{FILE_SUFFIX}"))
    selected: list[dict[str, Any]] = []
    for path in files:
        stamp = path.name[len(FILE_PREFIX) : -len(FILE_SUFFIX)]
        try:
            day = datetime.strptime(stamp, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < start_day:
            continue
        for record in _iter_file(path):
            if event_prefix and not str(record.get("event", "")).startswith(
                event_prefix
            ):
                continue
            if since is not None:
                ts = _parse_ts(str(record.get("ts", "")))
                if ts is None or ts < since:
                    continue
            selected.append(record)
    return selected[-limit:] if limit > 0 else selected


def _iter_file(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка по событиям: HTTP-статусы, время, маршруты ответов, ошибки."""

    http = [e for e in events if e.get("event") == "http.request"]
    asks = [e for e in events if e.get("event") == "support.ask"]
    errors = [e for e in events if str(e.get("event", "")).endswith("error")]

    http_ms = [float(e["duration_ms"]) for e in http if "duration_ms" in e]
    ask_ms = [float(e["response_time_ms"]) for e in asks if "response_time_ms" in e]
    status_counts: dict[str, int] = {}
    slow_paths: dict[str, list[float]] = {}
    for e in http:
        bucket = f"{str(e.get('status', '?'))[:1]}xx"
        status_counts[bucket] = status_counts.get(bucket, 0) + 1
        if "duration_ms" in e:
            slow_paths.setdefault(str(e.get("route") or e.get("path")), []).append(
                float(e["duration_ms"])
            )

    def _count(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in items:
            value = str(item.get(key, "?"))
            result[value] = result.get(value, 0) + 1
        return result

    escalated = sum(1 for e in asks if e.get("escalated"))
    return {
        "events": len(events),
        "http": {
            "requests": len(http),
            "by_status": status_counts,
            "p50_ms": _percentile(http_ms, 0.5),
            "p95_ms": _percentile(http_ms, 0.95),
            "slowest_routes": sorted(
                (
                    {"route": route, "count": len(ms), "p95_ms": _percentile(ms, 0.95)}
                    for route, ms in slow_paths.items()
                ),
                key=lambda item: item["p95_ms"] or 0,
                reverse=True,
            )[:10],
        },
        "support": {
            "asks": len(asks),
            "by_mode": _count(asks, "mode"),
            "by_provider": _count(asks, "provider"),
            "by_route_reason": _count(asks, "route_reason"),
            "escalation_rate": round(escalated / len(asks), 3) if asks else None,
            "p50_ms": _percentile(ask_ms, 0.5),
            "p95_ms": _percentile(ask_ms, 0.95),
        },
        "errors": {"count": len(errors), "by_event": _count(errors, "event")},
    }


class Timer:
    """Секундомер в миллисекундах для событий."""

    def __init__(self) -> None:
        self._started = time.perf_counter()

    def ms(self) -> int:
        return max(0, int((time.perf_counter() - self._started) * 1000))
