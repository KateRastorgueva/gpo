"""Прогрев кэша векторного поиска встроенной базы.

Считает эмбеддинги всех фрагментов (``knowledge_chunk``) и складывает их в кэш
dense-слоя (``DENSE_CACHE_DIR``, том ``app-dense``). Без прогрева первые запросы
считают векторы на лету и отвечают медленно.

Кодировщик берётся из настроек: если заданы ``LMSTUDIO_BASE_URL`` и
``LMSTUDIO_EMBEDDINGS_MODEL`` — bge-m3 через LM Studio, иначе локальный
rubert-mini (``DENSE_*``).

Запуск внутри контейнера backend::

    docker compose cp scripts/warm_dense_cache.py backend:/app/warm_dense_cache.py
    docker compose exec -T backend python /app/warm_dense_cache.py

Флаг ``--dry-run`` показывает, сколько векторов посчитается, и ничего не пишет.
"""

from __future__ import annotations

import argparse
import sys
import time

from sqlmodel import Session, select

from app.core.db import engine
from app.models import KnowledgeChunk, KnowledgeDoc, KnowledgeSource
from app.services import dense_local


def collect_texts(session: Session) -> dict[str, str]:
    """Ключ кэша → текст фрагмента (с заголовком владельца)."""
    source_titles = {
        row.id: row.title for row in session.exec(select(KnowledgeSource)).all()
    }
    doc_titles = {row.id: row.title for row in session.exec(select(KnowledgeDoc)).all()}
    texts: dict[str, str] = {}
    chunks = session.exec(select(KnowledgeChunk)).all()
    for chunk in chunks:
        if chunk.source_id is not None:
            title = source_titles.get(chunk.source_id, "")
        else:
            title = doc_titles.get(chunk.doc_id, "")
        text = dense_local.document_text(title, chunk.content)
        texts[dense_local.text_key(text)] = text
    return texts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with Session(engine) as session:
        texts = collect_texts(session)

    print(f"фрагментов: {len(texts)}", flush=True)
    if not dense_local.model_available():
        print("кодировщик не настроен", file=sys.stderr)
        return 1
    encoder = dense_local.get_encoder()
    cache = dense_local.get_cache()
    if encoder is None or cache is None:
        print(f"кодировщик недоступен: {dense_local.encoder_error()}", file=sys.stderr)
        return 1
    _, missing = cache.lookup(list(texts))
    print(
        f"кодировщик: {encoder.name} ({encoder.dim} измерений) | "
        f"уже в кэше: {len(texts) - len(missing)} | посчитать: {len(missing)}",
        flush=True,
    )
    if args.dry_run:
        return 0

    started = time.monotonic()
    batch = 500
    keys = list(texts)
    for start in range(0, len(keys), batch):
        part = {key: texts[key] for key in keys[start : start + batch]}
        dense_local.embed_missing(part)
        done = min(start + batch, len(keys))
        print(f"  {done}/{len(keys)} за {time.monotonic() - started:.0f} с", flush=True)

    # Убираем векторы фрагментов, которых больше нет в базе: передаём полный
    # набор ключей (пустой словарь с keep_only стёр бы весь кэш).
    dense_local.embed_missing(texts, keep_only=True)
    print(
        f"готово: векторов в кэше {cache.size()} за {time.monotonic() - started:.0f} с",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
