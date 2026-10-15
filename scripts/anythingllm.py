# ruff: noqa: T201  -- CLI-скрипт, вывод в консоль и есть результат
"""Загрузка документов в AnythingLLM и прогон тех же эталонных вопросов.

Ключ берётся из ANYTHINGLLM_API_KEY (окружение или .env), значение не печатается.

Примеры:
    python scripts/anythingllm.py reset
    python scripts/anythingllm.py upload "tusur docs" --max-pages 200
    python scripts/anythingllm.py eval --out result.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemini_file_search import GOLDEN, ROOT, SYSTEM_PROMPT  # noqa: E402

BASE = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001")
WORKSPACE = os.environ.get("ANYTHINGLLM_WORKSPACE", "tusur")


def load_key() -> str:
    key = os.environ.get("ANYTHINGLLM_API_KEY")
    env_path = ROOT / ".env"
    if not key and env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANYTHINGLLM_API_KEY="):
                key = line.partition("=")[2].split(" #")[0].strip().strip("\"'")
    if not key:
        sys.exit("ANYTHINGLLM_API_KEY не найден ни в окружении, ни в .env")
    return key


def client() -> httpx.Client:
    return httpx.Client(
        base_url=f"{BASE}/api/v1",
        headers={"Authorization": f"Bearer {load_key()}"},
        timeout=900,
    )


def ensure_workspace(c: httpx.Client) -> None:
    slugs = {w["slug"] for w in c.get("/workspaces").json().get("workspaces", [])}
    if WORKSPACE not in slugs:
        c.post("/workspace/new", json={"name": WORKSPACE}).raise_for_status()
    # Режим query: отвечать только по документам, иначе честный отказ.
    c.post(
        f"/workspace/{WORKSPACE}/update",
        json={
            "chatMode": "query",
            "openAiTemp": 0.1,
            "topN": 8,
            # Тот же промпт, что у Gemini: маркер НЕТ_ОТВЕТА уводит к оператору.
            "openAiPrompt": SYSTEM_PROMPT,
        },
    ).raise_for_status()


def _pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return 0


def cmd_upload(args: argparse.Namespace) -> None:
    c = client()
    ensure_workspace(c)
    for path in sorted(Path(args.folder).glob("*.pdf")):
        pages = _pdf_pages(path)
        row: dict[str, object] = {"file": path.name, "pages": pages}
        if args.max_pages and pages > args.max_pages:
            row["status"] = "skipped-large"
            print(json.dumps(row, ensure_ascii=False), flush=True)
            continue
        started = time.time()
        try:
            with path.open("rb") as fh:
                resp = c.post(
                    "/document/upload",
                    files={"file": (path.name, fh, "application/pdf")},
                )
            resp.raise_for_status()
            docs = resp.json().get("documents") or []
            locations = [d["location"] for d in docs if d.get("location")]
            words = sum(int(d.get("wordCount") or 0) for d in docs)
            c.post(
                f"/workspace/{WORKSPACE}/update-embeddings",
                json={"adds": locations, "deletes": []},
            ).raise_for_status()
            row.update(status="ok" if locations else "no-text", words=words)
        except Exception as exc:  # noqa: BLE001
            row["status"] = f"error: {type(exc).__name__}: {str(exc)[:200]}"
        row["seconds"] = round(time.time() - started, 1)
        print(json.dumps(row, ensure_ascii=False), flush=True)


def ask(c: httpx.Client, question: str) -> dict:  # type: ignore[type-arg]
    started = time.time()
    body = c.post(
        f"/workspace/{WORKSPACE}/chat", json={"message": question, "mode": "query"}
    ).json()
    titles: list[str] = []
    for src in body.get("sources") or []:
        title = str(src.get("title") or "")
        if title and title not in titles:
            titles.append(title)
    return {
        "question": question,
        "answer": str(body.get("textResponse") or "").strip(),
        "sources": titles,
        "seconds": round(time.time() - started, 1),
    }


def cmd_reset(_args: argparse.Namespace) -> None:
    # Нужен после смены модели эмбеддингов: старые векторы несовместимы.
    c = client()
    c.delete(f"/workspace/{WORKSPACE}")
    ensure_workspace(c)
    print(f"workspace {WORKSPACE} пересоздан")


def cmd_eval(args: argparse.Namespace) -> None:
    c = client()
    rows = []
    for question, doc, _keywords in GOLDEN:
        try:
            row = ask(c, question)
        except Exception as exc:  # noqa: BLE001
            row = {"question": question, "error": f"{type(exc).__name__}: {exc}"}
        answer = row.get("answer", "")
        no_answer = not row.get("sources") or answer.startswith(
            "There is no relevant information"
        )
        if doc is None:
            row["pass"] = no_answer
        else:
            row["pass"] = (not no_answer) and any(
                doc.lower() in s.lower() for s in row.get("sources", [])
            )
        row["expected_doc"] = doc
        rows.append(row)
        status = "PASS" if row["pass"] else "FAIL"
        print(f"{status}  {row.get('seconds', '-')}s  {question}", flush=True)
    print(f"\nИтог: {sum(r['pass'] for r in rows)}/{len(rows)}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("upload")
    p.add_argument("folder")
    p.add_argument("--max-pages", type=int, default=0)
    p.set_defaults(fn=cmd_upload)

    p = sub.add_parser("reset")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("eval")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_eval)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
