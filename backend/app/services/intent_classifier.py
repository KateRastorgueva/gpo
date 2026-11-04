"""Тема вопроса от классификатора Кати (отдельный контейнер ``intent_service``).

Классификатор не отвечает на вопросы: он только называет одну из 24 тем
(стипендия, общежитие, ГПО…) и уверенность. Тема пишется в журнал запросов,
видна оператору в очереди и попадает в метрики по темам.

Настройки меняет админ в «Управление → Настройки → Классификатор тем»
(реестр ``app_config``): включён ли, порог уверенности, адрес сервиса.
По умолчанию выключен.

Любая ошибка (сервис не поднят, таймаут, мусор в ответе) не мешает ответу
пользователю: обращение просто сохраняется без темы.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.app_config import live_settings

logger = logging.getLogger(__name__)

# Классификация на CPU занимает десятки миллисекунд; больше ждать не стоит,
# чтобы медленный сервис не тормозил ответы.
TIMEOUT_SECONDS = 2.0

# Копия intent_service/categories.py: нужна для подписей в метриках и очереди,
# даже когда сервис выключен.
CATEGORY_LABELS: dict[str, str] = {
    "akademicheskiy_otpusk": "Академический отпуск",
    "dopolnitelnoe_obrazovanie": "Дополнительное образование",
    "fakultety": "Факультеты и кафедры",
    "gpo": "ГПО",
    "lgoty": "Льготы",
    "materialnaya_pomoshch": "Материальная помощь",
    "medpunkt": "Медпункт",
    "mezhdunarodnoe": "Международная деятельность",
    "nauka": "Наука",
    "obshchaga": "Общежитие",
    "olimpiady": "Олимпиады",
    "oplata": "Оплата обучения",
    "postuplenie": "Поступление",
    "praktika": "Практика",
    "profkom": "Профком",
    "psiholog": "Психологическая помощь",
    "sport": "Спорт",
    "stipendiya": "Стипендия",
    "studencheskaya_zhizn": "Студенческая жизнь",
    "studotryady": "Студотряды",
    "trudoustroystvo": "Трудоустройство",
    "tusur_info": "О ТУСУРе",
    "ucheba": "Учёба",
    "volonterstvo": "Волонтёрство",
}


def label_for(intent: str | None) -> str | None:
    if intent is None:
        return None
    return CATEGORY_LABELS.get(intent, intent)


@dataclass
class IntentConfig:
    enabled: bool
    threshold: float
    service_url: str


@dataclass
class IntentResult:
    intent: str | None
    confidence: float
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def get_config() -> IntentConfig:
    threshold = float(live_settings.INTENT_CLASSIFIER_THRESHOLD)
    return IntentConfig(
        enabled=bool(live_settings.INTENT_CLASSIFIER_ENABLED),
        threshold=min(1.0, max(0.0, threshold)),
        service_url=str(live_settings.INTENT_CLASSIFIER_URL).strip().rstrip("/"),
    )


def check_health(config: IntentConfig) -> tuple[bool, bool, str | None]:
    """(сервис ответил, модель загружена, текст ошибки)."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.get(f"{config.service_url}/health")
            response.raise_for_status()
            body = response.json()
    except Exception as exc:  # noqa: BLE001 - показываем причину в админке
        return False, False, f"{type(exc).__name__}: {exc}"
    loaded = bool(body.get("ok"))
    return True, loaded, None if loaded else (body.get("error") or "model not loaded")


def classify(question: str, config: IntentConfig) -> IntentResult:
    """Спрашивает сервис. Тема ниже порога возвращается как ``intent=None``."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{config.service_url}/classify", json={"text": question, "top_k": 3}
            )
            response.raise_for_status()
            body = response.json()
        intent = str(body["category"])
        confidence = min(1.0, max(0.0, float(body["confidence"])))
        candidates = list(body.get("candidates") or [])
    except Exception as exc:  # noqa: BLE001 - классификатор не должен ронять ответ
        return IntentResult(
            intent=None, confidence=0.0, error=f"{type(exc).__name__}: {exc}"
        )
    if confidence < config.threshold:
        return IntentResult(intent=None, confidence=confidence, candidates=candidates)
    return IntentResult(intent=intent, confidence=confidence, candidates=candidates)


def classify_for_request(question: str) -> tuple[str | None, float | None]:
    """Тема для записи в журнал: (None, None), если классификатор выключен."""
    try:
        config = get_config()
    except Exception:  # noqa: BLE001 - кривое значение в настройках
        logger.warning("intent classifier settings unavailable", exc_info=True)
        return None, None
    if not config.enabled:
        return None, None
    result = classify(question, config)
    if result.error:
        logger.warning("intent classifier failed: %s", result.error)
        return None, None
    return result.intent, round(result.confidence, 4)
