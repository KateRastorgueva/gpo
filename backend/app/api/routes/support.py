from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    MyQueuePublic,
    SupportAskRequest,
    SupportAskResponse,
    SupportHistoryPublic,
)
from app.services.support_service import (
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

