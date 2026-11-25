"""Альтернативный классификатор тем: TF-IDF-модель по базе Help Desk ТУСУР.

Отличие от основного движка (``kate``, rubert-tiny2 на 24 студенческих темах):
этот обучен на 99 000 вопросов Help Desk и знает 22 темы **IT-сервисов** ТУСУР
(«Личный кабинет», «Журнал посещаемости», «Облачное хранилище», «Бронирование
помещений»…). Таксономии не пересекаются, поэтому движок включается
переключателем, а не заменяет модель Кати.

Артефакт — ``models/helpdesk_tfidf.npz``: словарь терминов, idf, веса
логистической регрессии и классы. Он портативный (без pickled-объектов sklearn),
поэтому загрузка считается прямо на numpy: версия scikit-learn в контейнере
ни на что не влияет. Обучение — ``scripts/train_intent_helpdesk.py``.

Идентификатор темы (``category``) — стабильный слаг от русского названия,
чтобы его можно было хранить в журнале запросов и показывать в метриках.
"""

from __future__ import annotations

import math
import os
import re
import threading
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_MODEL_PATH = Path(__file__).parent / "models" / "helpdesk_tfidf.npz"
MODEL_PATH = Path(os.environ.get("HELPDESK_MODEL_PATH", DEFAULT_MODEL_PATH))

# Тот же токенайзер, что у TfidfVectorizer по умолчанию.
_TOKEN_RE = re.compile(r"(?u)\b\w\w+\b")

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_lock = threading.Lock()
_terms: dict[str, int] = {}
_idf: np.ndarray | None = None
_coef: np.ndarray | None = None
_intercept: np.ndarray | None = None
_classes: list[str] = []
_categories: list[dict[str, str]] = []
_sublinear = True
_error: str | None = None


def slugify(name: str) -> str:
    """«Журнал посещаемости ТУСУР» -> ``zhurnal_poseshchaemosti_tusur``."""
    lowered = name.lower()
    latin = "".join(_TRANSLIT.get(char, char) for char in lowered)
    slug = re.sub(r"[^a-z0-9]+", "_", latin).strip("_")
    return slug or "category"


def _build_categories(classes: list[str]) -> list[dict[str, str]]:
    seen: dict[str, int] = {}
    result: list[dict[str, str]] = []
    for label in classes:
        slug = slugify(label)
        if slug in seen:
            seen[slug] += 1
            slug = f"{slug}_{seen[slug]}"
        else:
            seen[slug] = 0
        result.append({"name": slug, "label": label})
    return result


def load() -> None:
    """Загружает артефакт один раз; ошибка запоминается и отдаётся в /health."""
    global _terms, _idf, _coef, _intercept, _classes, _categories, _sublinear, _error
    if _coef is not None or _error is not None:
        return
    with _lock:
        if _coef is not None or _error is not None:
            return
        if not MODEL_PATH.exists():
            _error = f"model file not found: {MODEL_PATH}"
            return
        try:
            with np.load(MODEL_PATH, allow_pickle=False) as bundle:
                terms = [str(term) for term in bundle["terms"]]
                indices = bundle["term_indices"]
                _terms = {
                    term: int(idx) for term, idx in zip(terms, indices, strict=True)
                }
                _idf = bundle["idf"].astype(np.float32)
                _coef = bundle["coef"].astype(np.float32)
                _intercept = bundle["intercept"].astype(np.float32)
                _classes = [str(name) for name in bundle["classes"]]
                _sublinear = bool(int(bundle["sublinear"][0]))
            _categories = _build_categories(_classes)
        except Exception as exc:  # noqa: BLE001 - причина видна в /health
            _error = f"{type(exc).__name__}: {exc}"


def is_loaded() -> bool:
    return _coef is not None


def last_error() -> str | None:
    return _error


def categories() -> list[dict[str, str]]:
    return list(_categories)


def _vectorize(text: str) -> np.ndarray:
    """TF-IDF (1–2 граммы, sublinear tf, L2) — как у TfidfVectorizer."""
    assert _idf is not None
    tokens = _TOKEN_RE.findall(text.lower())
    counts: dict[int, float] = {}
    for token, column in ((t, _terms[t]) for t in tokens if t in _terms):
        counts[column] = counts.get(column, 0.0) + 1.0
    for first, second in zip(tokens, tokens[1:], strict=False):
        column = _terms.get(f"{first} {second}")
        if column is not None:
            counts[column] = counts.get(column, 0.0) + 1.0
    vector = np.zeros(_idf.shape[0], dtype=np.float32)
    for column, value in counts.items():
        weight = 1.0 + math.log(value) if _sublinear else value
        vector[column] = weight * _idf[column]
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm else vector


def predict(text: str, top_k: int) -> list[tuple[str, str, float]]:
    """Возвращает [(slug, label, confidence), …] по убыванию уверенности."""
    if _coef is None or _intercept is None:
        raise RuntimeError(_error or "model is not loaded")
    scores = _coef @ _vectorize(text) + _intercept
    scores = scores - float(scores.max())
    probabilities = np.exp(scores)
    probabilities /= float(probabilities.sum())
    order = np.argsort(-probabilities)[:top_k]
    by_label = {item["label"]: item["name"] for item in _categories}
    return [
        (
            by_label.get(_classes[i], slugify(_classes[i])),
            _classes[i],
            float(probabilities[i]),
        )
        for i in order
    ]
