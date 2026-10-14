# ruff: noqa: T201  -- CLI-скрипт, вывод в консоль и есть результат
"""Приёмочная проверка локального AnythingLLM (без Google).

Запуск:
    ANYTHINGLLM_API_KEY=... python scripts/check_anythingllm_local.py
    ANYTHINGLLM_API_KEY=... python scripts/check_anythingllm_local.py --app

Каждая проверка печатает PASS/FAIL. Код выхода 0 только если прошли все.
Флаг --app дополнительно проверяет ответ через бэкенд проекта
(нужен запущенный стек и RAG_PROVIDER=anythingllm в .env).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anythingllm as allm  # noqa: E402
from gemini_file_search import GOLDEN, ROOT  # noqa: E402

SCAN_DOCS = ("Izmeneniya_", "Ustav_FGAOU_TUSUR_24")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def check_settings(c: httpx.Client) -> None:
    s = c.get("/system").json()["settings"]
    engine = str(s.get("EmbeddingEngine"))
    model = str(s.get("EmbeddingModelPref"))
    llm = str(s.get("LLMProvider"))
    check("эмбеддинги локальные", engine in {"ollama", "lmstudio"}, engine)
    check("модель эмбеддингов bge-m3", "bge-m3" in model.lower(), model)
    check("LLM локальная, не gemini", llm in {"ollama", "lmstudio"}, llm)


def check_ocr_env() -> None:
    out = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "anythingllm",
            "printenv",
            "TARGET_OCR_LANG",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.strip()
    check("OCR с русским языком", "rus" in out, out or "переменная не задана")


def check_workspace(c: httpx.Client) -> None:
    w = c.get(f"/workspace/{allm.WORKSPACE}").json()["workspace"]
    w = w[0] if isinstance(w, list) else w
    docs = w.get("documents", [])
    names = [d["docpath"].split("/")[-1] for d in docs]
    check("в workspace не меньше 16 документов", len(docs) >= 16, str(len(docs)))
    scans = sum(any(n.startswith(p) for n in names) for p in SCAN_DOCS)
    check("сканы проиндексированы", scans >= 2, f"{scans} из 2 групп")
    check("режим query", w.get("chatMode") == "query", str(w.get("chatMode")))


def check_golden(c: httpx.Client) -> None:
    total = scans_ok = scans_all = offtopic_ok = offtopic_all = 0
    for question, doc, _ in GOLDEN:
        row = allm.ask(c, question)
        answer = row["answer"]
        no_answer = not row["sources"] or "НЕТ_ОТВЕТА" in answer.upper()
        if doc is None:
            ok = no_answer
            offtopic_all += 1
            offtopic_ok += ok
        else:
            ok = (not no_answer) and any(
                doc.lower() in s.lower() for s in row["sources"]
            )
            if doc.startswith(SCAN_DOCS):
                scans_all += 1
                scans_ok += ok
        total += ok
        print(f"   {'ok ' if ok else 'MISS'} {row['seconds']:>5}s  {question}")
    check("эталонные вопросы >= 15/17", total >= 15, f"{total}/{len(GOLDEN)}")
    check("вопросы по сканам >= 2/3", scans_ok >= 2, f"{scans_ok}/{scans_all}")
    check(
        "вопросы не по теме уходят в отказ",
        offtopic_ok == offtopic_all,
        f"{offtopic_ok}/{offtopic_all}",
    )


def check_app() -> None:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.split(" #")[0].strip().strip("\"'")
    check(
        "RAG_PROVIDER=anythingllm в .env",
        env.get("RAG_PROVIDER") == "anythingllm",
        env.get("RAG_PROVIDER", ""),
    )
    base = "http://localhost:8000/api/v1"
    token = httpx.post(
        f"{base}/login/access-token",
        data={
            "username": env["FIRST_SUPERUSER"],
            "password": env["FIRST_SUPERUSER_PASSWORD"],
        },
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    body = httpx.post(
        f"{base}/support/ask",
        json={"question": "Сколько длится академическая пара?"},
        headers=headers,
        timeout=300,
    ).json()
    refs = [s.get("source_ref") or "" for s in body.get("sources", [])]
    check(
        "приложение отвечает через RAG",
        body.get("mode") == "rag",
        str(body.get("route_reason")),
    )
    check(
        "источник от AnythingLLM",
        any(r.startswith("anythingllm:") for r in refs),
        str(refs[:1]),
    )
    off = httpx.post(
        f"{base}/support/ask",
        json={"question": "Посоветуй рецепт борща"},
        headers=headers,
        timeout=300,
    ).json()
    check(
        "вопрос не по теме уходит оператору",
        off.get("mode") == "operator",
        str(off.get("route_reason")),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("ANYTHINGLLM_API_KEY"):
        sys.exit("Задайте ANYTHINGLLM_API_KEY")
    c = allm.client()
    check_settings(c)
    check_ocr_env()
    check_workspace(c)
    check_golden(c)
    if args.app:
        check_app()
    failed = [name for name, ok, _ in results if not ok]
    print(f"\nИтог: {len(results) - len(failed)}/{len(results)} проверок")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
