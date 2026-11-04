"""Фильтр офтопа: отказать вежливо, не заводя запись в очереди оператора.

Два независимых признака, что вопрос не про университет:

1. Правила «мусора» (``junk_rule``) — не требуют ни модели, ни базы: пустой
   ввод без букв, одна повторяющаяся буква, набор в неверной раскладке
   («ghbdtn»). Работают для любого движка ответов.
2. Среднее сходство лучших фрагментов (``mean_top_similarity``): среднее
   косинусов top-N документов к вопросу (rubert-mini-frida из векторной
   добавки). Чем дальше вопрос от всей базы знаний, тем ниже среднее. Работает,
   только когда включена векторная добавка (``DENSE_SEARCH_ENABLED``) и
   используется встроенный поиск (legacy / search_only): у внешних движков
   (Gemini File Search, AnythingLLM) наши косинусы недоступны.

Порог и переключатель живут в «Управление → Настройки» (группа
``@ksup/offtopic``), по умолчанию фильтр выключен.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

REFUSAL_TEXT = (
    "Похоже, этот вопрос не относится к учёбе и жизни в университете, поэтому "
    "я не нашёл на него ответа в документах ТУСУР. Попробуйте переформулировать "
    "вопрос. Если он всё же по теме и нужен живой человек, нажмите "
    "«Передать оператору»."
)

REASON_JUNK_EMPTY = "junk_empty"
REASON_JUNK_REPEAT = "junk_repeat"
REASON_JUNK_LAYOUT = "junk_layout"
REASON_LOW_SIMILARITY = "offtopic_low_similarity"

# Раскладка ЙЦУКЕН ↔ QWERTY: «ghbdtn» → «привет».
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
_RU = "йцукенгшщзхъфывапролджэячсмитьбюё"
_EN_TO_RU = str.maketrans(_EN, _RU)

# Корни слов, которые встречаются в вопросах студентов. Достаточно одного
# совпадения после перекодировки, чтобы счесть латиницу русским текстом.
_RU_STEMS = (
    "привет",
    "здравств",
    "помог",
    "как ",
    "что ",
    "где ",
    "когда",
    "сколько",
    "стипенд",
    "общежит",
    "экзамен",
    "сесси",
    "академ",
    "отпуск",
    "расписан",
    "справк",
    "заявлен",
    "оплат",
    "обучен",
    "перевод",
    "отчисл",
    "диплом",
    "зачёт",
    "зачет",
    "документ",
    "пропуск",
    "студент",
    "деканат",
    "тусур",
)

_LETTER_RE = re.compile(r"[A-Za-zА-Яа-яЁё]")
_LATIN_ONLY_RE = re.compile(r"^[A-Za-z\s\[\];',.`]+$")


def junk_rule(question: str) -> str | None:
    """Причина, по которой вопрос — мусор, или None, если правила ничего не нашли."""

    text = question.strip()
    letters = _LETTER_RE.findall(text)
    if len(letters) < 2:
        return REASON_JUNK_EMPTY

    lowered = "".join(letters).lower()
    # «ааааааа», «ыыыы»: одна буква составляет почти весь ввод.
    if len(lowered) >= 4 and len(set(lowered)) == 1:
        return REASON_JUNK_REPEAT
    if len(lowered) >= 8 and len(set(lowered)) <= 2:
        return REASON_JUNK_REPEAT

    # Раскладка: только латиница, но после перекодировки получается русский.
    if len(letters) >= 4 and _LATIN_ONLY_RE.match(text):
        converted = text.lower().translate(_EN_TO_RU)
        if any(stem in f"{converted} " for stem in _RU_STEMS):
            return REASON_JUNK_LAYOUT
    return None


def mean_top_similarity(cosines: Sequence[float], top_n: int = 5) -> float | None:
    """Среднее top-N косинусов (по убыванию); None, если считать не из чего."""

    top = sorted(cosines, reverse=True)[: max(1, top_n)]
    if not top:
        return None
    return sum(top) / len(top)


def is_offtopic_by_similarity(
    cosines: Sequence[float], threshold: float, top_n: int = 5
) -> tuple[bool, float | None]:
    """(офтоп ли, среднее сходство). Без косинусов решения нет: не офтоп."""

    mean = mean_top_similarity(cosines, top_n)
    if mean is None:
        return False, None
    return mean < threshold, mean
