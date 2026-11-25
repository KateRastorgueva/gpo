"""Классификатор тем в админке: состояние сервиса, переключатель движка, проверка.

Включение, порог и адрес меняются в «Настройки → Классификатор тем»
(реестр ``app_config``); выбор движка — здесь, вкладка «Классификатор тем».

Движки: ``kate`` — модель Кати на 24 студенческих темах; ``helpdesk`` — TF-IDF
по базе Help Desk ТУСУР (22 темы IT-сервисов). Таксономии не пересекаются,
поэтому переключение меняет и список тем, и результат проверки.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import SessionDep, require_permission
from app.core.permissions import METRICS_READ, SETTINGS_MANAGE
from app.models import (
    IntentCandidatePublic,
    IntentCategoryPublic,
    IntentEngineOption,
    IntentEngineUpdate,
    IntentStatusPublic,
    IntentTestPublic,
    IntentTestRequest,
)
from app.services import app_config, intent_classifier

router = APIRouter(
    prefix="/admin/intent",
    tags=["admin-intent"],
    dependencies=[Depends(require_permission(METRICS_READ))],
)


def _status() -> IntentStatusPublic:
    config = intent_classifier.get_config()
    reachable, loaded, error = intent_classifier.check_health(config)
    health = intent_classifier.read_health(config) if reachable else None

    engines: list[IntentEngineOption] = []
    for item in (health or {}).get("engines") or []:
        name = str(item.get("name") or "")
        engines.append(
            IntentEngineOption(
                name=name,
                label=intent_classifier.ENGINE_LABELS.get(name, name),
                loaded=bool(item.get("loaded")),
                error=item.get("error"),
                categories=[
                    IntentCategoryPublic(
                        name=str(c.get("name") or ""), label=str(c.get("label") or "")
                    )
                    for c in item.get("categories") or []
                ],
            )
        )
    if not engines:
        # Сервис не ответил: показываем хотя бы основной движок с локальными темами.
        engines = [
            IntentEngineOption(
                name="kate",
                label=intent_classifier.ENGINE_LABELS["kate"],
                loaded=False,
                error=error,
                categories=[
                    IntentCategoryPublic(name=name, label=label)
                    for name, label in intent_classifier.CATEGORY_LABELS.items()
                ],
            )
        ]

    active = next((e for e in engines if e.name == config.engine), engines[0])
    return IntentStatusPublic(
        enabled=config.enabled,
        threshold=config.threshold,
        service_url=config.service_url,
        reachable=reachable,
        model_loaded=loaded,
        error=error,
        engine=config.engine,
        engines=engines,
        categories=active.categories,
    )


@router.get("/status", response_model=IntentStatusPublic)
def read_intent_status() -> Any:
    return _status()


@router.put(
    "/engine",
    response_model=IntentStatusPublic,
    dependencies=[Depends(require_permission(SETTINGS_MANAGE))],
)
def set_intent_engine(session: SessionDep, body: IntentEngineUpdate) -> Any:
    """Переключает движок классификатора (сохраняется в app_setting)."""
    try:
        app_config.apply_changes(session, values={"INTENT_ENGINE": body.engine})
    except app_config.SettingsValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": "Не удалось переключить движок", "errors": exc.errors},
        ) from exc
    return _status()


@router.post("/test", response_model=IntentTestPublic)
def test_intent(body: IntentTestRequest) -> Any:
    """Проверить вопрос, даже если классификатор выключен: в журнал не пишется."""
    config = intent_classifier.get_config()
    result = intent_classifier.classify(body.question, config)
    # У kate подписи тем локальные и стабильные; у helpdesk — из самой модели.
    use_local_labels = (result.engine or config.engine) == "kate"

    def label_for_candidate(candidate: dict[str, Any]) -> str:
        category = str(candidate.get("category", ""))
        if use_local_labels:
            return intent_classifier.label_for(category) or category
        return str(candidate.get("label") or "") or category

    intent_label = result.label
    if use_local_labels:
        intent_label = intent_classifier.label_for(result.intent)
    return IntentTestPublic(
        intent=result.intent,
        intent_label=intent_label,
        confidence=round(result.confidence, 4),
        threshold=config.threshold,
        candidates=[
            IntentCandidatePublic(
                category=str(c.get("category", "")),
                label=label_for_candidate(c),
                confidence=float(c.get("confidence", 0.0)),
            )
            for c in result.candidates
        ],
        error=result.error,
    )
