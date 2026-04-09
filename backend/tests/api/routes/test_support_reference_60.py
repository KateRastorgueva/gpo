import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import FaqEntryCreate
from app.services.support_service import RetrievalResult, create_faq_entry


FAQ_REFERENCE_20 = [
    "Где смотреть расписание занятий ТУСУР?",
    "Где посмотреть расписание пар ТУСУР?",
    "На каком сайте у ТУСУР расписание занятий?",
    "Где контакты приемной комиссии ТУСУР?",
    "Куда писать по вопросам поступления в ТУСУР?",
    "Где найти контакты для абитуриента ТУСУР?",
    "Где информация о стипендиях ТУСУР?",
    "Где смотреть меры поддержки студентов ТУСУР?",
    "Где официальные сведения о стипендиях ТУСУР?",
    "Где смотреть платные образовательные услуги ТУСУР?",
    "Где официальная информация по оплате обучения в ТУСУР?",
    "Где информация по договорам платного обучения ТУСУР?",
    "Где общие официальные сведения о ТУСУР?",
    "Где страница с общими сведениями об организации ТУСУР?",
    "Где сведения об образовательных программах ТУСУР?",
    "На какой странице ТУСУР размещены образовательные программы?",
    "Где раздел ТУСУР для студентов?",
    "Где на сайте ТУСУР страница для студентов?",
    "Где посмотреть полезные ссылки для студентов ТУСУР?",
    "Где найти расписание занятий и пар в ТУСУР?",
]

RAG_REFERENCE_20 = [
    "Какие сервисы доступны студентам в официальном разделе ТУСУР?",
    "Что указано в разделе ТУСУР для студентов?",
    "Какие документы описывают образовательные программы ТУСУР?",
    "Какая официальная информация доступна по образовательным программам ТУСУР?",
    "Какие сведения публикуются о платных образовательных услугах?",
    "Что можно узнать в официальном разделе ТУСУР по оплате обучения?",
    "Какие данные о стипендиях размещены на официальной странице ТУСУР?",
    "Где искать официальные сведения о мерах поддержки студентов?",
    "Какие контактные данные приемной комиссии есть в официальных источниках?",
    "Где в официальных источниках смотреть контакты для абитуриента?",
    "Какие официальные сведения об организации доступны на сайте ТУСУР?",
    "Какая структура официальных сведений указана на сайте ТУСУР?",
    "По каким страницам ТУСУР можно проверить базовые сведения для студента?",
    "Где посмотреть, какие разделы лучше использовать для справочной информации?",
    "Какие ссылки ТУСУР используются как первичные источники в поддержке?",
    "Какие официальные страницы ТУСУР относятся к учебному расписанию?",
    "Где на сайте ТУСУР искать сведения об образовании и программах?",
    "Что рекомендовано как источник по вопросам поступления в ТУСУР?",
    "Какие разделы ТУСУР подходят для проверки платного обучения?",
    "Какие официальные источники использовать для студенческих вопросов?",
]

OPERATOR_REFERENCE_20 = [
    "Назовите точный дедлайн оплаты моего договора в этом семестре",
    "Какой номер приказа по моему индивидуальному учебному плану?",
    "Прими решение, можно ли мне не платить до конца месяца",
    "Скажи точную дату из приказа для моего факультета",
    "Подтверди юридически, что меня не отчислят при просрочке оплаты",
    "Рассчитай точную сумму и срок оплаты по моему договору",
    "Дай официальный вывод по спору с деканатом",
    "Подтверди без ссылок, что приказ уже подписан",
    "Скажи, какой штраф будет у меня лично за просрочку",
    "Назови точный дедлайн подачи документов именно для моей группы",
    "Выбери за меня правильный юридический вариант действий",
    "Подтверди, что мой договор действует без ограничений",
    "Дай точный ответ по моему судебному вопросу с университетом",
    "Скажи итог по регламенту без указания источников",
    "Гарантируй, что мне одобрят отсрочку оплаты",
    "Назови точный номер приказа и дату вступления в силу",
    "Реши, могу ли я нарушить регламент без последствий",
    "Дай обязательное к исполнению решение по платежам",
    "Подтверди юридически мой особый порядок оплаты",
    "Прими официальное решение по моему индивидуальному кейсу",
]


def _fake_retrieval_results() -> list[RetrievalResult]:
    return [
        RetrievalResult(
            source_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            source_title="Reference source",
            source_ref="https://tusur.ru/ru",
            chunk_id=None,
            snippet="Официальные источники университета",
            score=0.93,
        ),
        RetrievalResult(
            source_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            source_title="Reference source 2",
            source_ref="https://tusur.ru/sveden/common",
            chunk_id=None,
            snippet="Данные из официального раздела",
            score=0.86,
        ),
    ]


def test_reference_sets_have_60_questions() -> None:
    assert len(FAQ_REFERENCE_20) == 20
    assert len(RAG_REFERENCE_20) == 20
    assert len(OPERATOR_REFERENCE_20) == 20
    assert len(FAQ_REFERENCE_20 + RAG_REFERENCE_20 + OPERATOR_REFERENCE_20) == 60


def test_reference_faq_questions_route_to_faq(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    for idx, question in enumerate(FAQ_REFERENCE_20):
        create_faq_entry(
            db,
            FaqEntryCreate(
                question=question,
                answer=f"FAQ answer {idx}",
                is_active=True,
            ),
        )

    for question in FAQ_REFERENCE_20:
        response = client.post(
            f"{settings.API_V1_STR}/support/ask",
            headers=normal_user_token_headers,
            json={"question": question, "channel": "web"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "faq"


def test_reference_rag_questions_route_to_rag(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    fake_results = _fake_retrieval_results()
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch(
            "app.services.support_service.retrieve_relevant_chunks",
            return_value=fake_results,
        ),
        patch(
            "app.services.support_service.generate_answer",
            return_value=("Ответ по источникам", False),
        ),
    ):
        for question in RAG_REFERENCE_20:
            response = client.post(
                f"{settings.API_V1_STR}/support/ask",
                headers=normal_user_token_headers,
                json={"question": question, "channel": "web"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["mode"] == "rag"


def test_reference_operator_questions_route_to_operator(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.services.support_service.find_faq_match", return_value=(None, 0.0)),
        patch("app.services.support_service.retrieve_relevant_chunks", return_value=[]),
    ):
        for question in OPERATOR_REFERENCE_20:
            response = client.post(
                f"{settings.API_V1_STR}/support/ask",
                headers=normal_user_token_headers,
                json={"question": question, "channel": "web"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["mode"] == "operator"
