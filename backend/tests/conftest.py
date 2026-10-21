import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    ActiveRequest,
    AppSetting,
    DocTag,
    IngestItem,
    IngestJob,
    Item,
    KnowledgeArchive,
    KnowledgeCategory,
    KnowledgeChunk,
    KnowledgeDoc,
    KnowledgeSource,
    KnowledgeTag,
    SupportAnswer,
    SupportFeedback,
    SupportRequest,
    SupportTicket,
    Tag,
    User,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

TEST_DB_SUFFIX = "_test"
ALLOW_DESTRUCTIVE_TESTS_ENV = "ALLOW_DESTRUCTIVE_TESTS"


def _assert_isolated_test_database() -> None:
    """Защита от прогона тестов против рабочей базы.

    Фикстура `db` ниже удаляет все строки из основных таблиц, поэтому тесты обязаны
    работать на отдельной базе (имя с суффиксом `_test`). Осознанный прогон против
    рабочей базы возможен только через явный ALLOW_DESTRUCTIVE_TESTS=1.
    """
    database = settings.POSTGRES_DB
    if database.endswith(TEST_DB_SUFFIX) or os.getenv(ALLOW_DESTRUCTIVE_TESTS_ENV) == "1":
        return
    raise RuntimeError(
        f"Refusing to run tests against database {database!r}: the test session deletes "
        "all rows from app_user, item, faqentry, knowledge_source, knowledge_chunk, "
        "request_journal, answer_journal and support_ticket.\n"
        f"Use a dedicated database, for example `POSTGRES_DB={database}{TEST_DB_SUFFIX} "
        "bash scripts/tests-start.sh`, or set "
        f"{ALLOW_DESTRUCTIVE_TESTS_ENV}=1 if destructive run is really intended."
    )


_assert_isolated_test_database()


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session
        session.execute(delete(SupportTicket))
        session.execute(delete(SupportFeedback))
        session.execute(delete(SupportAnswer))
        # Явно, до удаления запросов: у active_request FK на журнал и на app_user
        session.execute(delete(ActiveRequest))
        session.execute(delete(SupportRequest))
        session.execute(delete(KnowledgeTag))
        session.execute(delete(DocTag))
        session.execute(delete(KnowledgeChunk))
        session.execute(delete(KnowledgeArchive))
        session.execute(delete(KnowledgeSource))
        session.execute(delete(KnowledgeDoc))
        session.execute(delete(Tag))
        session.execute(delete(KnowledgeCategory))
        session.execute(delete(IngestItem))
        session.execute(delete(IngestJob))
        session.execute(delete(AppSetting))
        statement = delete(Item)
        session.execute(statement)
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
