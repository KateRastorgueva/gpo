"""Классификатор тем в админке: состояние сервиса и проверка вопроса.

Включение, порог и адрес меняются в «Настройки → Классификатор тем»
(реестр ``app_config``); здесь только то, чего форма настроек не умеет.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import require_permission
from app.core.permissions import METRICS_READ
from app.models import (
    IntentCandidatePublic,
    IntentCategoryPublic,
    IntentStatusPublic,
    IntentTestPublic,
    IntentTestRequest,
)
from app.services import intent_classifier

router = APIRouter(
    prefix="/admin/intent",
    tags=["admin-intent"],
    dependencies=[Depends(require_permission(METRICS_READ))],
)


@router.get("/status", response_model=IntentStatusPublic)
def read_intent_status() -> Any:
    config = intent_classifier.get_config()
    reachable, loaded, error = intent_classifier.check_health(config)
    return IntentStatusPublic(
        enabled=config.enabled,
        threshold=config.threshold,
        service_url=config.service_url,
        reachable=reachable,
        model_loaded=loaded,
        error=error,
        categories=[
            IntentCategoryPublic(name=name, label=label)
            for name, label in intent_classifier.CATEGORY_LABELS.items()
        ],
    )


@router.post("/test", response_model=IntentTestPublic)
def test_intent(body: IntentTestRequest) -> Any:
    """Проверить вопрос, даже если классификатор выключен: в журнал не пишется."""
    config = intent_classifier.get_config()
    result = intent_classifier.classify(body.question, config)
    return IntentTestPublic(
        intent=result.intent,
        intent_label=intent_classifier.label_for(result.intent),
        confidence=round(result.confidence, 4),
        threshold=config.threshold,
        candidates=[
            IntentCandidatePublic(
                category=str(c.get("category", "")),
                label=intent_classifier.label_for(str(c.get("category", ""))) or "",
                confidence=float(c.get("confidence", 0.0)),
            )
            for c in result.candidates
        ],
        error=result.error,
    )
