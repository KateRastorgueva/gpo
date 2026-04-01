import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import col, delete, func, select

from app.api.deps import SessionDep, get_current_active_superuser
from app.models import (
    FaqEntriesPublic,
    FaqEntry,
    FaqEntryCreate,
    FaqEntryPublic,
    FaqEntryUpdate,
    KnowledgeSource,
    KnowledgeSourcePublic,
    KnowledgeSourcesPublic,
    Message,
    OperatorQueuePublic,
    ReindexRequest,
    ReindexResponse,
)
from app.services.support_service import (
    create_faq_entry,
    index_source,
    list_operator_queue,
    remove_source_vectors,
    reindex_sources,
    resolve_source_content,
    update_faq_entry,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin-support"],
    dependencies=[Depends(get_current_active_superuser)],
)


@router.get("/faq", response_model=FaqEntriesPublic)
def list_faq(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    count_statement = select(func.count()).select_from(FaqEntry)
    count = session.exec(count_statement).one()
    statement = select(FaqEntry).order_by(col(FaqEntry.created_at).desc()).offset(
        skip
    ).limit(limit)
    faq_entries = session.exec(statement).all()
    return FaqEntriesPublic(data=faq_entries, count=count)


@router.post("/faq", response_model=FaqEntryPublic)
def create_faq(session: SessionDep, faq_in: FaqEntryCreate) -> Any:
    return create_faq_entry(session, faq_in)


@router.patch("/faq/{faq_id}", response_model=FaqEntryPublic)
def update_faq(
    *, session: SessionDep, faq_id: uuid.UUID, faq_in: FaqEntryUpdate
) -> Any:
    faq = session.get(FaqEntry, faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ entry not found")
    return update_faq_entry(session, faq, faq_in)


@router.delete("/faq/{faq_id}", response_model=Message)
def delete_faq(*, session: SessionDep, faq_id: uuid.UUID) -> Any:
    faq = session.get(FaqEntry, faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ entry not found")
    session.delete(faq)
    session.commit()
    return Message(message="FAQ entry deleted successfully")


@router.get("/sources", response_model=KnowledgeSourcesPublic)
def list_sources(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    count_statement = select(func.count()).select_from(KnowledgeSource)
    count = session.exec(count_statement).one()
    statement = (
        select(KnowledgeSource)
        .order_by(col(KnowledgeSource.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    sources = session.exec(statement).all()
    return KnowledgeSourcesPublic(data=sources, count=count)


@router.post("/sources/upload", response_model=KnowledgeSourcePublic)
async def upload_source(
    *,
    session: SessionDep,
    title: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    manual_content: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
) -> Any:
    file_bytes: bytes | None = None
    filename: str | None = None
    if file is not None:
        file_bytes = await file.read()
        filename = file.filename

    try:
        content, source_type, source_ref = resolve_source_content(
            filename=filename,
            file_bytes=file_bytes,
            source_url=source_url,
            manual_content=manual_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read source: {exc}")

    source_title = title or source_ref or "Manual source"
    source = KnowledgeSource(
        title=source_title,
        source_type=source_type,  # type: ignore[arg-type]
        source_ref=source_ref,
        content=content,
        status="pending",
        is_active=True,
    )
    session.add(source)
    session.commit()
    session.refresh(source)

    try:
        index_source(session, source)
    except Exception as exc:
        session.rollback()
        source = session.get(KnowledgeSource, source.id) or source
        source.status = "failed"
        session.add(source)
        session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to index source: {exc}")
    session.refresh(source)
    return source


@router.delete("/sources/{source_id}", response_model=Message)
def delete_source(*, session: SessionDep, source_id: uuid.UUID) -> Any:
    source = session.get(KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    try:
        remove_source_vectors(source_id)
    except Exception:
        # Keep delete operation non-blocking for DB consistency.
        pass
    session.exec(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
    session.commit()
    return Message(message="Source deleted successfully")


@router.post("/sources/reindex", response_model=ReindexResponse)
def reindex_knowledge_sources(
    *, session: SessionDep, body: ReindexRequest | None = None
) -> Any:
    source_ids = body.source_ids if body else None
    reindexed = reindex_sources(session, source_ids=source_ids)
    return ReindexResponse(
        message="Reindex completed successfully", reindexed_sources=reindexed
    )


@router.get("/operator-queue", response_model=OperatorQueuePublic)
def get_operator_queue(session: SessionDep) -> Any:
    queue = list_operator_queue(session)
    return OperatorQueuePublic(data=queue, count=len(queue))
