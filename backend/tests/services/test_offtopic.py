"""Фильтр офтопа: правила «мусора» и порог среднего сходства."""

import pytest

from app.services import offtopic


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("   ", offtopic.REASON_JUNK_EMPTY),
        ("12345 ???", offtopic.REASON_JUNK_EMPTY),
        ("😀😀😀", offtopic.REASON_JUNK_EMPTY),
        ("ааааааа", offtopic.REASON_JUNK_REPEAT),
        ("ыыыы ыыы", offtopic.REASON_JUNK_REPEAT),
        ("ghbdtn", offtopic.REASON_JUNK_LAYOUT),  # «привет»
        ("rfr jajhvbnm fmflvbxtcrbq jngecr", offtopic.REASON_JUNK_LAYOUT),
        ("cnbgtylbz", offtopic.REASON_JUNK_LAYOUT),  # «стипендия»
    ],
)
def test_junk_rule_flags_garbage(text: str, reason: str) -> None:
    assert offtopic.junk_rule(text) == reason


@pytest.mark.parametrize(
    "text",
    [
        "Как оформить академический отпуск?",
        "Где смотреть расписание занятий ТУСУР?",
        "Какой рецепт борща самый вкусный?",  # офтоп, но не мусор: решает сходство
        "How do I apply for a dormitory?",
        "ТУСУР",
        "ФДО",
    ],
)
def test_junk_rule_keeps_real_questions(text: str) -> None:
    assert offtopic.junk_rule(text) is None


def test_mean_top_similarity_uses_best_n() -> None:
    assert offtopic.mean_top_similarity(
        [0.1, 0.5, 0.4, 0.3, 0.2, 0.9], 5
    ) == pytest.approx((0.9 + 0.5 + 0.4 + 0.3 + 0.2) / 5)
    assert offtopic.mean_top_similarity([], 5) is None


def test_threshold_boundary_and_missing_cosines() -> None:
    # Ровно на пороге вопрос остаётся «по теме»: отказ только строго ниже.
    assert offtopic.is_offtopic_by_similarity([0.30] * 5, 0.30) == (
        False,
        pytest.approx(0.30),
    )
    assert offtopic.is_offtopic_by_similarity([0.29] * 5, 0.30)[0] is True
    assert (
        offtopic.is_offtopic_by_similarity([0.8, 0.7, 0.1, 0.1, 0.1], 0.30)[0] is False
    )
    # Без косинусов решения нет: не трогаем вопрос.
    assert offtopic.is_offtopic_by_similarity([], 0.30) == (False, None)
