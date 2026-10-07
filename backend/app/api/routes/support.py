from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    MyQueuePublic,
    SupportAskRequest,
    SupportAskResponse,
    SupportFeedbackCreate,
    SupportFeedbackPublic,
    SupportHistoryPublic,
)
from app.services.support_service import (
    SupportConflictError,
    create_feedback,
    list_my_queue,
    list_support_history,
    run_support_pipeline,
)

router = APIRouter(prefix="/support", tags=["support"])


@router.post("/ask", response_model=SupportAskResponse)
def ask_support_question(
    *, session: SessionDep, current_user: CurrentUser, payload: SupportAskRequest
) -> Any:
    return run_support_pipeline(
        session=session, user_id=current_user.id, payload=payload
    )


@router.get("/history", response_model=SupportHistoryPublic)
def get_support_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    session_id: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    history = list_support_history(
        session=session, user_id=current_user.id, session_id=session_id, limit=limit
    )
    return SupportHistoryPublic(data=history, count=len(history))


@router.get("/my-queue", response_model=MyQueuePublic)
def get_my_queue(*, session: SessionDep, current_user: CurrentUser) -> Any:
    items = list_my_queue(session, current_user.id)
    return MyQueuePublic(data=items, count=len(items))


@router.post("/feedback", response_model=SupportFeedbackPublic)
def submit_support_feedback(
    *, session: SessionDep, current_user: CurrentUser, payload: SupportFeedbackCreate
) -> Any:
    """Отзыв на свой запрос: один отзыв на запрос (решение V7)."""
    try:
        return create_feedback(session, user_id=current_user.id, payload=payload)
    except SupportConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        # Чужой запрос отвечает так же, как несуществующий
        raise HTTPException(status_code=404, detail=str(exc))
