"""Админка внешних RAG-движков: переключатель, пакетная загрузка, список документов."""

import uuid
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.config import settings
from app.core.permissions import KNOWLEDGE_READ, KNOWLEDGE_WRITE
from app.models import (
    EngineDocumentsPublic,
    IngestItem,
    IngestJob,
    IngestJobCreate,
    IngestJobPublic,
    IngestJobsPublic,
    RagProviderOption,
    RagProviderPublic,
    RagProviderUpdate,
)
from app.services import rag_ingest, rag_providers

router = APIRouter(prefix="/admin/rag", tags=["admin-rag"])


def _provider_public(session: SessionDep) -> RagProviderPublic:
    return RagProviderPublic(
        active=rag_providers.get_active_provider(session),
        default=settings.RAG_PROVIDER,
        options=[
            RagProviderOption(
                name=name,
                label=label,
                configured=rag_providers.is_provider_configured(name),
            )
            for name, label in rag_providers.PROVIDER_LABELS.items()
        ],
    )


@router.get(
    "/provider",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=RagProviderPublic,
)
def get_rag_provider(session: SessionDep) -> Any:
    return _provider_public(session)


@router.put(
    "/provider",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=RagProviderPublic,
)
def set_rag_provider(session: SessionDep, body: RagProviderUpdate) -> Any:
    if not rag_providers.is_provider_configured(body.provider):
        raise HTTPException(
            status_code=400,
            detail=f"Движок {body.provider} не настроен: нет ключа или хранилища (Управление → Настройки)",
        )
    rag_providers.set_active_provider(session, body.provider)
    return _provider_public(session)


@router.get(
    "/documents",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=EngineDocumentsPublic,
)
def list_engine_documents(engine: Literal["gemini", "anythingllm"]) -> Any:
    provider = "gemini_file_search" if engine == "gemini" else "anythingllm"
    configured = rag_providers.is_provider_configured(provider)
    if not configured:
        return EngineDocumentsPublic(engine=engine, configured=False, data=[], count=0)
    try:
        docs = (
            rag_providers.list_gemini_documents()
            if engine == "gemini"
            else rag_providers.list_anythingllm_documents()
        )
    except Exception as exc:  # noqa: BLE001 — показываем ошибку движка в админке
        return EngineDocumentsPublic(
            engine=engine,
            configured=True,
            error=f"{type(exc).__name__}: {exc}"[:500],
            data=[],
            count=0,
        )
    docs.sort(key=lambda d: d.name.lower())
    return EngineDocumentsPublic(
        engine=engine, configured=True, data=docs, count=len(docs)
    )


@router.post(
    "/ingest/jobs",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=IngestJobPublic,
)
def create_ingest_job(
    session: SessionDep, current_user: CurrentUser, body: IngestJobCreate
) -> Any:
    engines = {"gemini": ("gemini_file_search",), "anythingllm": ("anythingllm",)}
    needed = engines.get(body.target, ("gemini_file_search", "anythingllm"))
    missing = [p for p in needed if not rag_providers.is_provider_configured(p)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Не настроены движки: {', '.join(missing)} (ключи в .env)",
        )
    job = IngestJob(target=body.target, total=body.total, created_by=current_user.id)
    session.add(job)
    session.commit()
    session.refresh(job)
    return rag_ingest.job_public(session, job)


def _job_or_404(session: SessionDep, job_id: uuid.UUID) -> IngestJob:
    job = session.get(IngestJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingest job not found")
    return job


@router.post(
    "/ingest/jobs/{job_id}/files",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=IngestJobPublic,
)
def upload_ingest_file(
    *,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    job_id: uuid.UUID,
    file: UploadFile = File(...),
) -> Any:
    job = _job_or_404(session, job_id)
    uploaded = session.exec(
        select(func.count()).select_from(IngestItem).where(IngestItem.job_id == job.id)
    ).one()
    if uploaded >= job.total:
        raise HTTPException(
            status_code=409, detail="All files of this job are uploaded"
        )
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than {settings.MAX_UPLOAD_SIZE_MB} MB",
        )
    if not data:
        raise HTTPException(status_code=400, detail="File is empty")
    rag_ingest.add_item(session, job, file.filename or "document", data)
    background_tasks.add_task(rag_ingest.drain_queue)
    return rag_ingest.job_public(session, job)


@router.get(
    "/ingest/jobs",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=IngestJobsPublic,
)
def list_ingest_jobs(session: SessionDep, limit: int = 10) -> Any:
    jobs = session.exec(
        select(IngestJob).order_by(col(IngestJob.created_at).desc()).limit(limit)
    ).all()
    count = session.exec(select(func.count()).select_from(IngestJob)).one()
    return IngestJobsPublic(
        data=[rag_ingest.job_public(session, job) for job in jobs], count=count
    )


@router.get(
    "/ingest/jobs/{job_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=IngestJobPublic,
)
def get_ingest_job(session: SessionDep, job_id: uuid.UUID) -> Any:
    return rag_ingest.job_public(session, _job_or_404(session, job_id))
