import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import col, delete

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.config import settings
from app.core.permissions import (
    KNOWLEDGE_READ,
    KNOWLEDGE_WRITE,
    METRICS_READ,
    TAXONOMY_WRITE,
    TICKET_READ,
    TICKET_RESOLVE,
)
from app.models import (
    ActiveRequestsPublic,
    FaqEntriesPublic,
    FaqEntryCreate,
    FaqEntryPublic,
    FaqEntryUpdate,
    JournalRequestsPublic,
    KnowledgeArchiveListPublic,
    KnowledgeCategoriesPublic,
    KnowledgeCategoryCreate,
    KnowledgeCategoryPublic,
    KnowledgeCategoryUpdate,
    KnowledgeDocCreate,
    KnowledgeDocPublic,
    KnowledgeDocsPublic,
    KnowledgeDocUpdate,
    KnowledgeSearchPublic,
    KnowledgeSearchRequest,
    KnowledgeSource,
    KnowledgeSourcePublic,
    KnowledgeSourcesPublic,
    KnowledgeSourceUpdate,
    KnowledgeSourceUploadRequest,
    Message,
    ReindexRequest,
    ReindexResponse,
    SupportMetricsPublic,
    SupportTicketPublic,
    SupportTicketsPublic,
    TagCreate,
    TagPublic,
    TagsPublic,
    TicketAssignRequest,
    TicketReopenRequest,
    TicketResolveRequest,
)
from app.services.support_service import (
    SupportConflictError,
    assign_ticket,
    create_category,
    create_doc,
    create_faq_entry,
    create_tag,
    deactivate_source,
    delete_category,
    delete_doc,
    delete_tag,
    get_category,
    get_doc,
    get_doc_public,
    get_faq_entry,
    get_source_public,
    get_support_metrics,
    get_ticket,
    index_doc,
    index_source,
    list_active_requests,
    list_categories,
    list_docs,
    list_faq_entries,
    list_journal_requests,
    list_knowledge_archive,
    list_operator_queue,
    list_tags,
    reindex_knowledge,
    remove_source_vectors,
    reopen_ticket,
    resolve_source_content,
    resolve_ticket,
    search_knowledge,
    update_category,
    update_doc_metadata,
    update_faq_entry,
    update_source_metadata,
)
from app.services.support_service import (
    list_sources as list_sources_with_taxonomy,
)

router = APIRouter(prefix="/admin", tags=["admin-support"])


def _create_and_index_source(
    *,
    session: SessionDep,
    title: str | None,
    source_type: str,
    source_ref: str | None,
    content: str,
) -> KnowledgeSourcePublic:
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
        status_code = 400 if isinstance(exc, ValueError) else 500
        raise HTTPException(
            status_code=status_code, detail=f"Failed to index source: {exc}"
        )
    session.refresh(source)
    return get_source_public(session, source)


@router.get(
    "/faq",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=FaqEntriesPublic,
)
def list_faq(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """FAQ-фасад над базой знаний: записи с `source_type='faq'`."""
    data, count = list_faq_entries(session, skip=skip, limit=limit)
    return FaqEntriesPublic(data=data, count=count)


@router.post(
    "/faq",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=FaqEntryPublic,
)
def create_faq(session: SessionDep, faq_in: FaqEntryCreate) -> Any:
    return create_faq_entry(session, faq_in)


@router.patch(
    "/faq/{faq_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=FaqEntryPublic,
)
def update_faq(
    *, session: SessionDep, faq_id: uuid.UUID, faq_in: FaqEntryUpdate
) -> Any:
    faq = get_faq_entry(session, faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ entry not found")
    return update_faq_entry(session, faq, faq_in)


@router.delete(
    "/faq/{faq_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=Message,
)
def delete_faq(*, session: SessionDep, faq_id: uuid.UUID) -> Any:
    faq = get_faq_entry(session, faq_id)
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ entry not found")
    try:
        remove_source_vectors(faq_id)
    except Exception:
        # FAQ-запись могла не попадать в индекс: удаление не должно блокироваться.
        pass
    session.delete(faq)
    session.commit()
    return Message(message="FAQ entry deleted successfully")


@router.get(
    "/sources",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=KnowledgeSourcesPublic,
)
def list_sources(
    session: SessionDep,
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    source_type: str | None = None,
    exclude_type: str | None = None,
) -> Any:
    data, count = list_sources_with_taxonomy(
        session,
        skip=skip,
        limit=limit,
        search=search,
        source_type=source_type,
        exclude_type=exclude_type,
    )
    return KnowledgeSourcesPublic(data=data, count=count)


@router.post(
    "/sources/upload",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=KnowledgeSourcePublic,
)
def upload_source(
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
        # Синхронный обработчик: FastAPI выполняет его в threadpool, и долгая
        # индексация не блокирует event loop воркера.
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        file_bytes = file.file.read(max_bytes + 1)
        if len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File is larger than {settings.MAX_UPLOAD_SIZE_MB} MB",
            )
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
    return _create_and_index_source(
        session=session,
        title=title,
        source_type=source_type,
        source_ref=source_ref,
        content=content,
    )


@router.post(
    "/sources/upload-json",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=KnowledgeSourcePublic,
)
def upload_source_json(
    *, session: SessionDep, payload: KnowledgeSourceUploadRequest
) -> Any:
    try:
        content, source_type, source_ref = resolve_source_content(
            filename=None,
            file_bytes=None,
            source_url=payload.source_url,
            manual_content=payload.manual_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read source: {exc}")

    return _create_and_index_source(
        session=session,
        title=payload.title,
        source_type=source_type,
        source_ref=source_ref,
        content=content,
    )


@router.delete(
    "/sources/{source_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=Message,
)
def delete_source(*, session: SessionDep, source_id: uuid.UUID) -> Any:
    source = session.get(KnowledgeSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    try:
        remove_source_vectors(source_id)
    except Exception:
        # Keep delete operation non-blocking for DB consistency.
        pass
    session.exec(delete(KnowledgeSource).where(col(KnowledgeSource.id) == source_id))
    session.commit()
    return Message(message="Source deleted successfully")


@router.post(
    "/sources/reindex",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=ReindexResponse,
)
def reindex_knowledge_sources(
    *, session: SessionDep, body: ReindexRequest | None = None
) -> Any:
    source_ids = body.source_ids if body else None
    full_rebuild = body.full_rebuild if body else False
    purge_orphans = body.purge_orphans if body else True
    # Полная пересборка пересоздаёт коллекцию Qdrant, поэтому переиндексирует оба корпуса
    reindexed, reindexed_docs, orphan_vectors_removed = reindex_knowledge(
        session,
        source_ids=source_ids,
        include_docs=full_rebuild,
        full_rebuild=full_rebuild,
        purge_orphans=purge_orphans,
    )
    return ReindexResponse(
        message="Reindex completed successfully",
        reindexed_sources=reindexed,
        reindexed_docs=reindexed_docs,
        orphan_vectors_removed=orphan_vectors_removed,
        full_rebuild=full_rebuild,
    )


@router.get(
    "/operator-queue",
    dependencies=[Depends(require_permission(TICKET_READ))],
    response_model=SupportTicketsPublic,
)
def get_operator_queue(session: SessionDep) -> Any:
    """Тикеты поддержки (включая решённые — их можно переоткрыть)."""
    tickets = list_operator_queue(session)
    return SupportTicketsPublic(data=tickets, count=len(tickets))


def _ticket_or_404(session: SessionDep, ticket_id: uuid.UUID) -> Any:
    ticket = get_ticket(session, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    return ticket


@router.post(
    "/tickets/{ticket_id}/assign",
    dependencies=[Depends(require_permission(TICKET_RESOLVE))],
    response_model=SupportTicketPublic,
)
def assign_support_ticket(
    *,
    session: SessionDep,
    ticket_id: uuid.UUID,
    payload: TicketAssignRequest,
) -> Any:
    ticket = _ticket_or_404(session, ticket_id)
    try:
        return assign_ticket(session, ticket, assigned_to=payload.assigned_to)
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/tickets/{ticket_id}/resolve",
    dependencies=[Depends(require_permission(TICKET_RESOLVE))],
    response_model=SupportTicketPublic,
)
def resolve_support_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID,
    payload: TicketResolveRequest,
) -> Any:
    """Ответ оператора: решение уходит в журнал шагом `human`, запрос выходит из очереди."""
    ticket = _ticket_or_404(session, ticket_id)
    try:
        return resolve_ticket(
            session, ticket, resolution=payload.resolution, actor_id=current_user.id
        )
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/tickets/{ticket_id}/reopen",
    dependencies=[Depends(require_permission(TICKET_RESOLVE))],
    response_model=SupportTicketPublic,
)
def reopen_support_ticket(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    ticket_id: uuid.UUID,
    payload: TicketReopenRequest | None = None,
) -> Any:
    """Переоткрытие: создаётся новый тикет, запрос возвращается в очередь."""
    ticket = _ticket_or_404(session, ticket_id)
    try:
        return reopen_ticket(
            session,
            ticket,
            reason=payload.reason if payload else None,
            actor_id=current_user.id,
        )
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get(
    "/metrics",
    dependencies=[Depends(require_permission(METRICS_READ))],
    response_model=SupportMetricsPublic,
)
def get_admin_support_metrics(session: SessionDep) -> Any:
    return get_support_metrics(session)


@router.get(
    "/requests/active",
    dependencies=[Depends(require_permission(TICKET_READ))],
    response_model=ActiveRequestsPublic,
)
def get_active_requests(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """Запросы, которые сейчас висят в очереди (горячая таблица active_request)."""
    data, count = list_active_requests(session, skip=skip, limit=limit)
    return ActiveRequestsPublic(data=data, count=count)


@router.get(
    "/requests/journal",
    dependencies=[Depends(require_permission(TICKET_READ))],
    response_model=JournalRequestsPublic,
)
def get_journal_requests(
    session: SessionDep,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """Журнал запросов: все запросы, включая активные (источник правды)."""
    data, count = list_journal_requests(session, status=status, skip=skip, limit=limit)
    return JournalRequestsPublic(data=data, count=count)


@router.patch(
    "/sources/{source_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=KnowledgeSourcePublic,
)
def update_knowledge_source(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    source_id: uuid.UUID,
    source_in: KnowledgeSourceUpdate,
) -> Any:
    """Обновить метаданные источника: заголовок, категорию, активность, набор тэгов.

    `tags=[]` очищает набор, отсутствие поля `tags` — не трогает его.
    Перед изменением сохраняется снапшот предыдущей версии в архив.
    """
    source = session.get(KnowledgeSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    try:
        return update_source_metadata(
            session, source, source_in, archived_by=current_user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/sources/{source_id}/deactivate",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=KnowledgeSourcePublic,
)
def deactivate_knowledge_source(
    *, session: SessionDep, current_user: CurrentUser, source_id: uuid.UUID
) -> Any:
    """Мягкое удаление источника: он пропадает из поиска, история версий сохраняется.

    Жёсткое удаление (`DELETE /admin/sources/{id}`) по решению V6 уничтожает и архив.
    """
    source = session.get(KnowledgeSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    return deactivate_source(session, source, archived_by=current_user.id)


@router.get(
    "/sources/{source_id}/archive",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=KnowledgeArchiveListPublic,
)
def list_source_archive(session: SessionDep, source_id: uuid.UUID) -> Any:
    """История версий знания, свежие сверху."""
    if session.get(KnowledgeSource, source_id) is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    data, count = list_knowledge_archive(session, source_id)
    return KnowledgeArchiveListPublic(data=data, count=count)


@router.get(
    "/categories",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=KnowledgeCategoriesPublic,
)
def list_knowledge_categories(
    session: SessionDep, skip: int = 0, limit: int = 100
) -> Any:
    data, count = list_categories(session, skip=skip, limit=limit)
    return KnowledgeCategoriesPublic(data=data, count=count)


@router.post(
    "/categories",
    dependencies=[Depends(require_permission(TAXONOMY_WRITE))],
    response_model=KnowledgeCategoryPublic,
)
def create_knowledge_category(
    session: SessionDep, category_in: KnowledgeCategoryCreate
) -> Any:
    try:
        return create_category(session, category_in)
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.patch(
    "/categories/{category_id}",
    dependencies=[Depends(require_permission(TAXONOMY_WRITE))],
    response_model=KnowledgeCategoryPublic,
)
def update_knowledge_category(
    *,
    session: SessionDep,
    category_id: uuid.UUID,
    category_in: KnowledgeCategoryUpdate,
) -> Any:
    category = get_category(session, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Knowledge category not found")
    try:
        return update_category(session, category, category_in)
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete(
    "/categories/{category_id}",
    dependencies=[Depends(require_permission(TAXONOMY_WRITE))],
    response_model=Message,
)
def delete_knowledge_category(*, session: SessionDep, category_id: uuid.UUID) -> Any:
    """Удалить категорию. Источники остаются без категории (ON DELETE SET NULL)."""
    if not delete_category(session, category_id):
        raise HTTPException(status_code=404, detail="Knowledge category not found")
    return Message(message="Knowledge category deleted successfully")


@router.get(
    "/tags",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=TagsPublic,
)
def list_knowledge_tags(session: SessionDep, skip: int = 0, limit: int = 200) -> Any:
    data, count = list_tags(session, skip=skip, limit=limit)
    return TagsPublic(data=data, count=count)


@router.post(
    "/tags",
    dependencies=[Depends(require_permission(TAXONOMY_WRITE))],
    response_model=TagPublic,
)
def create_knowledge_tag(session: SessionDep, tag_in: TagCreate) -> Any:
    try:
        return create_tag(session, tag_in)
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete(
    "/tags/{tag_id}",
    dependencies=[Depends(require_permission(TAXONOMY_WRITE))],
    response_model=Message,
)
def delete_knowledge_tag(*, session: SessionDep, tag_id: uuid.UUID) -> Any:
    if not delete_tag(session, tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    return Message(message="Tag deleted successfully")


@router.post(
    "/knowledge/search",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=KnowledgeSearchPublic,
)
def search_knowledge_base(
    *, session: SessionDep, payload: KnowledgeSearchRequest
) -> Any:
    """Поиск по базе знаний с фильтрами по корпусу, категории и тэгам (решение D4)."""
    hits = search_knowledge(session, payload)
    return KnowledgeSearchPublic(data=hits, count=len(hits))


@router.get(
    "/docs",
    dependencies=[Depends(require_permission(KNOWLEDGE_READ))],
    response_model=KnowledgeDocsPublic,
)
def list_knowledge_docs(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    data, count = list_docs(session, skip=skip, limit=limit)
    return KnowledgeDocsPublic(data=data, count=count)


@router.post(
    "/docs",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=KnowledgeDocPublic,
)
def create_knowledge_doc(session: SessionDep, doc_in: KnowledgeDocCreate) -> Any:
    """Создать документ и сразу попытаться его проиндексировать (отдельный корпус, V4)."""
    doc = create_doc(session, doc_in)
    try:
        index_doc(session, doc)
    except Exception as exc:
        session.rollback()
        doc = get_doc(session, doc.id) or doc
        doc.status = "failed"
        session.add(doc)
        session.commit()
        raise HTTPException(status_code=500, detail=f"Failed to index document: {exc}")
    session.refresh(doc)
    return get_doc_public(session, doc)


@router.patch(
    "/docs/{doc_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=KnowledgeDocPublic,
)
def update_knowledge_doc(
    *, session: SessionDep, doc_id: uuid.UUID, doc_in: KnowledgeDocUpdate
) -> Any:
    doc = get_doc(session, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return update_doc_metadata(session, doc, doc_in)


@router.delete(
    "/docs/{doc_id}",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=Message,
)
def delete_knowledge_doc(*, session: SessionDep, doc_id: uuid.UUID) -> Any:
    if not delete_doc(session, doc_id):
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return Message(message="Knowledge document deleted successfully")


@router.post(
    "/docs/reindex",
    dependencies=[Depends(require_permission(KNOWLEDGE_WRITE))],
    response_model=ReindexResponse,
)
def reindex_knowledge_docs(
    *, session: SessionDep, body: ReindexRequest | None = None
) -> Any:
    """Переиндексация корпуса документов (источники не затрагиваются)."""
    doc_ids = body.doc_ids if body else None
    purge_orphans = body.purge_orphans if body else True
    _, reindexed_docs, orphan_vectors_removed = reindex_knowledge(
        session,
        doc_ids=doc_ids,
        include_sources=False,
        purge_orphans=purge_orphans,
    )
    return ReindexResponse(
        message="Documents reindex completed successfully",
        reindexed_sources=0,
        reindexed_docs=reindexed_docs,
        orphan_vectors_removed=orphan_vectors_removed,
    )
