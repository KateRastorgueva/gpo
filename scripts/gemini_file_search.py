"""Загрузка документов в Gemini File Search и проверка ответов.

Ключ берётся из GEMINI_API_KEY (или GOOGLE_API_KEY) в окружении или в .env
в корне проекта. Значение ключа скрипт никогда не печатает.

Примеры:
    python scripts/gemini_file_search.py create --name tusur-docs
    python scripts/gemini_file_search.py upload --store fileSearchStores/... "tusur docs"
    python scripts/gemini_file_search.py list --store fileSearchStores/...
    python scripts/gemini_file_search.py ask --store fileSearchStores/... "Как перевестись?"
    python scripts/gemini_file_search.py eval --store fileSearchStores/... --out result.json

Нужен пакет google-genai (pip install google-genai).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = {".pdf", ".txt", ".md", ".docx", ".html", ".htm", ".xlsx", ".csv"}
MAX_FILE_BYTES = 100 * 1024 * 1024  # лимит File Search на один файл

SYSTEM_PROMPT = (
    "Ты ассистент техподдержки университета ТУСУР. Отвечай только на основе "
    "найденных документов, кратко и по делу, на русском языке. Указывай, из какого "
    "документа взят ответ. Если в документах нет ответа на вопрос, ответь ровно "
    "одним словом НЕТ_ОТВЕТА и ничего больше."
)

# Эталонные вопросы: ожидаемый документ (часть имени файла) и ключевые слова ответа.
# None в doc означает «ответа в документах нет, должен уйти оператору».
GOLDEN = [
    ("Какие документы нужны для поступления в ТУСУР в 2026 году?", "Pravila_priema_2026", ["паспорт", "документ об образовании"]),
    ("Как восстановиться после отчисления?", "Poryadok_perevoda", ["восстановлен"]),
    ("Как перевестись на другое направление подготовки?", "Poryadok_perevoda", ["перевод"]),
    ("Сколько длится академическая пара и когда перерывы?", "Reghim_zanyatiy", ["минут"]),
    ("Как проводится текущий контроль успеваемости?", "Polozheniye_po_provedeniyu_tekushchego", ["контрол"]),
    ("Что такое внутренняя система оценки качества образования?", "Pologhenie_o_vnutrennei_sisteme", ["качеств"]),
    ("Какие права и обязанности есть у обучающихся по правилам внутреннего распорядка?", "Pravila_rasporyadka", ["обязан"]),
    ("Кто является учредителем ТУСУР?", "Ustav", ["учредител"]),
    ("Какие гарантии работникам предусмотрены коллективным договором?", "Kollektivnyi_dogovor", ["работник"]),
    ("Сколько студентов обучалось в ТУСУР по отчёту о самообследовании за 2024 год?", "Otchet_o_rezulytatax_samoobsledovaniya_za_2024", ["обучающ", "студент"]),
    ("Чем занимается отдел нормативного обеспечения?", "Pologhenie_ob_otdele_normativnogo", ["норматив"]),
    ("Как оформляется приостановление образовательных отношений, академический отпуск?", "Poryadok_oformleniya", ["академическ"]),
    # Сканы без текстового слоя: ответ есть только в картинках страниц.
    ("Какие изменения внесены в устав ТУСУР в марте 2020 года?", "Izmeneniya_v_ustav_TUSURa_16.03.2020", []),
    ("Какие изменения в устав ТУСУР утверждены в августе 2019 года?", "Izmeneniya_v_ustav_02_08_19", []),
    ("Какие органы управления ТУСУР указаны в уставе 2024 года?", "Ustav_FGAOU_TUSUR_24", ["совет", "ректор"]),
    ("Какая погода будет завтра в Томске?", None, []),
    ("Посоветуй рецепт борща", None, []),
]


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    env_path = ROOT / ".env"
    if not key and env_path.exists():
        values: dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, _, value = line.partition("=")
                values[name.strip()] = value.strip().strip('"').strip("'")
        key = values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY не найден ни в окружении, ни в .env")
    return key


def client() -> genai.Client:
    return genai.Client(api_key=load_key())


def cmd_create(args: argparse.Namespace) -> None:
    store = client().file_search_stores.create(config={"display_name": args.name})
    print(store.name)


def _wait(c: genai.Client, operation: types.UploadToFileSearchStoreOperation, timeout: int) -> bool:
    deadline = time.time() + timeout
    while not operation.done:
        if time.time() > deadline:
            return False
        time.sleep(3)
        operation = c.operations.get(operation)
    return operation.error is None


def cmd_upload(args: argparse.Namespace) -> None:
    c = client()
    existing = {doc.display_name for doc in c.file_search_stores.documents.list(parent=args.store)}
    paths = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in SUPPORTED)
    report = []
    for path in paths:
        size = path.stat().st_size
        row = {"file": path.name, "mb": round(size / 1024 / 1024, 1)}
        if path.name in existing:
            row["status"] = "already"
        elif size > MAX_FILE_BYTES:
            row["status"] = "too-big"
        else:
            started = time.time()
            try:
                op = c.file_search_stores.upload_to_file_search_store(
                    file=str(path),
                    file_search_store_name=args.store,
                    config={"display_name": path.name},
                )
                row["status"] = "ok" if _wait(c, op, args.timeout) else "failed-or-timeout"
            except Exception as exc:  # noqa: BLE001
                row["status"] = f"error: {type(exc).__name__}: {str(exc)[:200]}"
            row["seconds"] = round(time.time() - started, 1)
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)


def cmd_list(args: argparse.Namespace) -> None:
    for doc in client().file_search_stores.documents.list(parent=args.store):
        print(json.dumps({
            "name": doc.display_name,
            "state": str(doc.state),
            "bytes": doc.size_bytes,
        }, ensure_ascii=False))


def ask(c: genai.Client, store: str, model: str, question: str) -> dict:
    started = time.time()
    response = c.models.generate_content(
        model=model,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store], top_k=8))],
        ),
    )
    answer = (response.text or "").strip()
    meta = response.candidates[0].grounding_metadata if response.candidates else None
    titles: list[str] = []
    pages: list[int | None] = []
    for chunk in (meta.grounding_chunks or []) if meta else []:
        ctx = chunk.retrieved_context
        if ctx and ctx.title and ctx.title not in titles:
            titles.append(ctx.title)
            pages.append(ctx.page_number)
    return {
        "question": question,
        "answer": answer,
        "sources": titles,
        "pages": pages,
        "seconds": round(time.time() - started, 1),
    }


def cmd_ask(args: argparse.Namespace) -> None:
    print(json.dumps(ask(client(), args.store, args.model, args.question), ensure_ascii=False, indent=2))


def cmd_eval(args: argparse.Namespace) -> None:
    c = client()
    rows = []
    for question, doc, keywords in GOLDEN:
        try:
            row = ask(c, args.store, args.model, question)
        except Exception as exc:  # noqa: BLE001
            row = {"question": question, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        answer = row.get("answer", "").lower()
        no_answer = "нет_ответа" in answer or not row.get("sources")
        if doc is None:
            row["pass"] = no_answer
        else:
            source_ok = any(doc.lower() in s.lower() for s in row.get("sources", []))
            keyword_ok = any(k in answer for k in keywords) if keywords else True
            row["source_ok"] = source_ok
            row["keyword_ok"] = keyword_ok
            row["pass"] = (not no_answer) and source_ok
        row["expected_doc"] = doc
        rows.append(row)
        print(f"{'PASS' if row['pass'] else 'FAIL'}  {row.get('seconds', '-')}s  {question}", flush=True)
    passed = sum(r["pass"] for r in rows)
    print(f"\nИтог: {passed}/{len(rows)}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create"); p.add_argument("--name", default="tusur-docs"); p.set_defaults(fn=cmd_create)
    p = sub.add_parser("upload"); p.add_argument("--store", required=True); p.add_argument("folder")
    p.add_argument("--timeout", type=int, default=900); p.set_defaults(fn=cmd_upload)
    p = sub.add_parser("list"); p.add_argument("--store", required=True); p.set_defaults(fn=cmd_list)
    for name, fn in (("ask", cmd_ask), ("eval", cmd_eval)):
        p = sub.add_parser(name); p.add_argument("--store", required=True)
        p.add_argument("--model", default=os.environ.get("GEMINI_FILE_SEARCH_MODEL", "gemini-2.5-flash"))
        if name == "ask":
            p.add_argument("question")
        else:
            p.add_argument("--out")
        p.set_defaults(fn=fn)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
