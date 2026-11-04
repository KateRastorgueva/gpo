import os

from fastapi import APIRouter, Depends
from pydantic.networks import EmailStr

from app.api.deps import CurrentUser, SessionDep, require_permission
from app.core.permissions import USER_MANAGE
from app.models import Message
from app.services import rag_providers
from app.services.app_config import live_settings
from app.utils import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(require_permission(USER_MANAGE))],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> bool:
    return True


def _build_value(name: str) -> str:
    """Значение из окружения сборки; пусто или «unset» — это «unknown»."""
    value = (os.environ.get(name) or "").strip()
    return value if value and value.lower() != "unset" else "unknown"


@router.get("/version")
def get_version(_: CurrentUser, session: SessionDep) -> dict[str, str | bool]:
    """Какая сборка запущена и с какими ключевыми режимами RAG.

    GIT_SHA, GIT_BRANCH, BUILD_TIME приходят из build-аргументов образа
    (см. docs/build-version.md); без них возвращается «unknown».
    """
    sha = _build_value("GIT_SHA")
    return {
        "git_sha": sha,
        "git_sha_short": sha[:7] if sha != "unknown" else sha,
        "git_branch": _build_value("GIT_BRANCH"),
        "build_time": _build_value("BUILD_TIME"),
        "rag_provider": rag_providers.get_active_provider(session),
        "vector_search_enabled": bool(live_settings.VECTOR_SEARCH_ENABLED),
        "offtopic_filter_enabled": bool(live_settings.OFFTOPIC_FILTER_ENABLED),
    }
