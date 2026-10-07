import logging
import re

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlmodel import Session, select
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from app.core.config import settings
from app.core.db import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1

MAINTENANCE_DB = "postgres"
DB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def ensure_database_exists() -> None:
    """Создать целевую базу, если её ещё нет.

    Нужно для тестового прогона на отдельной базе: контейнер postgres создаёт только
    одну базу (POSTGRES_DB), а тесты обязаны работать не на рабочей (см. tests/conftest.py).
    """
    url = make_url(str(settings.SQLALCHEMY_DATABASE_URI))
    database = url.database
    if not database:
        raise RuntimeError("POSTGRES_DB is not set")
    if not DB_NAME_PATTERN.match(database):
        raise RuntimeError(f"Unsupported database name: {database!r}")

    admin_engine = create_engine(
        url.set(database=MAINTENANCE_DB), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database},
            ).first()
            if exists:
                logger.info("Database %s already exists", database)
                return
            # Имя базы нельзя параметризовать, поэтому оно проверено шаблоном выше.
            connection.execute(text(f'CREATE DATABASE "{database}"'))
            logger.info("Database %s created", database)
    finally:
        admin_engine.dispose()


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init(db_engine: Engine) -> None:
    try:
        ensure_database_exists()
        # Try to create session to check if DB is awake
        with Session(db_engine) as session:
            session.exec(select(1))
    except Exception as e:
        logger.error(e)
        raise e


def main() -> None:
    logger.info("Initializing service")
    init(engine)
    logger.info("Service finished initializing")


if __name__ == "__main__":
    main()
