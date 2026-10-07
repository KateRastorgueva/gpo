#! /usr/bin/env bash
set -e
set -x

# Тесты обязаны работать на отдельной базе: сессионная фикстура `db` очищает таблицы,
# поэтому прогон против рабочей базы уничтожил бы её данные.
export POSTGRES_DB="${TEST_POSTGRES_DB:-app_test}"

# Создаёт тестовую базу, если её ещё нет, и ждёт готовности PostgreSQL
python app/tests_pre_start.py

# prestart.sh мигрирует рабочую базу, а тестовой нужна своя схема на head
alembic upgrade head

bash scripts/test.sh "$@"
