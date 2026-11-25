"""Импорт статей Help Desk ТУСУР в базу знаний.

Файл — дамп с сайта ``help.tusur.ru/knowledgebase.php`` (например,
``tusur_kb_articles_with_text.json``)::

    {"base_url": "https://help.tusur.ru", "total_articles": 113,
     "articles": [{"title": "...", "url": "https://help.tusur.ru/knowledgebase.php?article=97",
                   "categories": ["..."], "text": "...", "chunks": [...], "status": "ok"}]}

Каждая статья становится **отдельным источником знаний**: ``title`` — название
статьи, ``source_ref`` — ссылка на её подраздел (``knowledgebase.php?article=N``),
``content`` — полный текст. Тогда в ответе RAG источник кликабелен и ведёт на
конкретную статью, а не на главную базу знаний.

Повторный запуск не дублирует: источник ищется по ``source_ref`` и обновляется
(текст и название), затем переиндексируется.

Запуск (внутри контейнера backend — там зависимости и доступ к БД)::

    docker compose cp tusur_kb_articles_with_text.json backend:/tmp/kb.json
    docker compose cp scripts/import_helpdesk_kb.py backend:/app/import_helpdesk_kb.py
    docker compose exec -T backend python /app/import_helpdesk_kb.py --json /tmp/kb.json

Полезные флаги: ``--dry-run`` (только показать), ``--limit N`` (первые N статей),
``--source-type`` (значение ``source_type``, по умолчанию ``url``).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Iterable
from typing import Any

from sqlmodel import Session, select

from app.core.db import engine
from app.models import KnowledgeSource
from app.services import support_service

TITLE_MAX = 255
REF_MAX = 1024


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def load_articles(path: pathlib.Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        articles = data.get("articles")
        if articles is None:
            raise SystemExit("В JSON нет ключа 'articles'")
        if not isinstance(articles, list):
            raise SystemExit("'articles' должен быть списком")
        return [item for item in articles if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise SystemExit("Неизвестный формат JSON")


def iter_valid(
    articles: Iterable[dict[str, Any]],
) -> Iterable[tuple[str, str, str]]:
    for item in articles:
        title = _clean(item.get("title") or "")
        url = str(item.get("url") or "").strip()
        text = str(item.get("text") or "").strip()
        status = str(item.get("status") or "ok").lower()
        if status != "ok" or not title or not url or not text:
            continue
        yield title[:TITLE_MAX], url[:REF_MAX], text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", required=True, type=pathlib.Path)
    parser.add_argument("--source-type", default="url")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.json.exists():
        print(f"Файл не найден: {args.json}", file=sys.stderr)
        return 1

    articles = list(iter_valid(load_articles(args.json)))
    if args.limit:
        articles = articles[: args.limit]
    print(f"статей к импорту: {len(articles)}")

    created = updated = chunks_total = 0
    with Session(engine) as session:
        for number, (title, url, text) in enumerate(articles, 1):
            source = session.exec(
                select(KnowledgeSource).where(KnowledgeSource.source_ref == url)
            ).first()
            action = "обновлён" if source else "создан"
            if args.dry_run:
                print(f"  [{number}/{len(articles)}] {action}: {title[:70]}")
                continue
            if source is None:
                source = KnowledgeSource(
                    title=title,
                    source_type=args.source_type,
                    source_ref=url,
                    content=text,
                    status="pending",
                    is_active=True,
                )
                created += 1
            else:
                source.title = title
                source.content = text
                source.source_type = args.source_type
                source.is_active = True
                updated += 1
            session.add(source)
            session.flush()
            chunks_total += support_service.index_source(session, source)
            if number % 20 == 0 or number == len(articles):
                print(
                    f"  [{number}/{len(articles)}] {action}: {title[:60]} "
                    f"(чанков всего: {chunks_total})"
                )

    if args.dry_run:
        print("dry-run: база не изменялась")
        return 0
    print(
        f"готово: создано {created}, обновлено {updated}, чанков {chunks_total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
