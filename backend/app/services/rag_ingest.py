"""Пакетная загрузка файлов во внешние RAG-движки с прогрессом.

Админ создаёт задание (``IngestJob``) на N файлов и отправляет файлы по одному
(nginx пропускает до 25 МБ на запрос). Каждый файл кладётся во временный каталог,
строка ``IngestItem`` получает статус ``queued``, а обработка идёт в фоне.

Backend работает в нескольких воркерах, поэтому очередь и прогресс живут в
Postgres, а обрабатывает очередь один воркер за раз (advisory lock): так
движки получают файлы последовательно и не перегружаются.
"""

import logging
import mimetypes
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, col, func, select

from app.core.db import engine
from app.models import (
    IngestItem,
    IngestItemPublic,
    IngestJob,
    IngestJobPublic,
    get_datetime_utc,
)
from app.services import rag_providers

logger = logging.getLogger(__name__)

# Произвольный, но постоянный ключ advisory lock для очереди загрузки.
INGEST_LOCK_KEY = 750_215_001
# Строка в статусе running дольше этого срока — воркер умер посреди обработки.
STALE_RUNNING_AFTER = timedelta(minutes=30)
INGEST_DIR = Path(tempfile.gettempdir()) / "rag-ingest"

TARGET_ENGINES = {
    "gemini": ("gemini",),
    "anythingllm": ("anythingllm",),
    "both": ("gemini", "anythingllm"),
}


def _item_path(item_id: uuid.UUID) -> Path:
    return INGEST_DIR / str(item_id)


def add_item(
    session: Session, job: IngestJob, filename: str, data: bytes
) -> IngestItem:
    INGEST_DIR.mkdir(parents=True, exist_ok=True)
    item = IngestItem(job_id=job.id, filename=filename, size_bytes=len(data))
    _item_path(item.id).write_bytes(data)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _queued_count(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(IngestItem)
        .where(IngestItem.status == "queued")
    ).one()


def _fail_stale_items(session: Session) -> None:
    cutoff = get_datetime_utc() - STALE_RUNNING_AFTER
    stale = session.exec(
        select(IngestItem).where(
            IngestItem.status == "running", col(IngestItem.started_at) < cutoff
        )
    ).all()
    for item in stale:
        item.status = "failed"
        item.error = "Обработка прервана (перезапуск backend)"
        item.finished_at = get_datetime_utc()
        session.add(item)
    session.commit()


def _process_item(session: Session, item: IngestItem, target: str) -> None:
    path = _item_path(item.id)
    errors: list[str] = []
    try:
        data = path.read_bytes()
    except OSError as exc:
        item.status = "failed"
        item.error = f"Файл не найден на сервере: {exc}"
        item.finished_at = get_datetime_utc()
        session.add(item)
        session.commit()
        return
    mime_type = mimetypes.guess_type(item.filename)[0] or "application/octet-stream"

    for engine_name in TARGET_ENGINES[target]:
        upload = (
            rag_providers.upload_gemini_document
            if engine_name == "gemini"
            else rag_providers.upload_anythingllm_document
        )
        try:
            status = upload(item.filename, data, mime_type)
        except Exception as exc:  # noqa: BLE001 — ошибка движка уходит в статус файла
            logger.warning(
                "Ingest %s -> %s failed: %s", item.filename, engine_name, exc
            )
            status = "error"
            errors.append(f"{engine_name}: {type(exc).__name__}: {exc}"[:600])
        setattr(item, f"{engine_name}_status", status)

    item.status = "failed" if errors else "done"
    item.error = "\n".join(errors)[:2000] or None
    item.finished_at = get_datetime_utc()
    session.add(item)
    session.commit()
    path.unlink(missing_ok=True)


def _claim_next(session: Session) -> tuple[IngestItem, str] | None:
    row = session.exec(
        select(IngestItem, IngestJob)
        .join(IngestJob, col(IngestJob.id) == col(IngestItem.job_id))
        .where(IngestItem.status == "queued")
        .order_by(col(IngestItem.created_at))
        .limit(1)
    ).first()
    if row is None:
        return None
    item, job = row
    item.status = "running"
    item.started_at = get_datetime_utc()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item, job.target


def drain_queue() -> None:
    """Фоновая задача: обработать все файлы в очереди, если очередь никто не держит.

    Задача, не получившая блокировку, просто выходит: держатель после
    освобождения ещё раз смотрит в очередь и подхватит её файл.
    """
    while True:
        with engine.connect() as lock_conn:
            locked = lock_conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": INGEST_LOCK_KEY}
            ).scalar()
            if not locked:
                return
            try:
                with Session(engine) as session:
                    _fail_stale_items(session)
                    while claimed := _claim_next(session):
                        _process_item(session, *claimed)
            finally:
                lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": INGEST_LOCK_KEY}
                )
                lock_conn.commit()
        with Session(engine) as session:
            if _queued_count(session) == 0:
                return


def job_public(session: Session, job: IngestJob) -> IngestJobPublic:
    items = session.exec(
        select(IngestItem)
        .where(IngestItem.job_id == job.id)
        .order_by(col(IngestItem.created_at))
    ).all()
    done = sum(1 for i in items if i.status == "done")
    failed = sum(1 for i in items if i.status == "failed")
    finished_items = [i for i in items if i.started_at and i.finished_at]
    remaining = job.total - done - failed
    eta: int | None = None
    if finished_items and remaining > 0:
        spent = sum(
            (i.finished_at - i.started_at).total_seconds()
            for i in finished_items
            if i.finished_at and i.started_at
        )
        eta = round(spent / len(finished_items) * remaining)
    return IngestJobPublic(
        id=job.id,
        target=job.target,
        total=job.total,
        uploaded=len(items),
        done=done,
        failed=failed,
        finished=remaining <= 0,
        eta_seconds=eta,
        created_at=job.created_at,
        items=[IngestItemPublic.model_validate(i, from_attributes=True) for i in items],
    )
