"""Подбор порогов маршрутизации RAG под текущий backend embeddings.

Запускается против поднятого стека с загруженными источниками. Берет размеченные
вопросы (answerable: в базе есть ответ; unanswerable: вне темы), снимает
top_score и число фрагментов выше порога из decision_metrics и подбирает порог
top_score, максимизирующий balanced accuracy. Вопросы калибровки не должны
совпадать с вопросами итоговой проверки.

Использование:
    python scripts/calibrate_routing.py questions.json --api http://localhost:8000/api/v1 \
        --user admin@example.com --password ...
questions.json: [{"q": "...", "answerable": true}, ...]
"""

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("questions")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    client = httpx.Client(timeout=120)
    token = client.post(
        f"{args.api}/login/access-token",
        data={"username": args.user, "password": args.password},
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    rows = []
    for item in json.load(open(args.questions, encoding="utf-8")):
        body = client.post(f"{args.api}/support/ask", json={"question": item["q"]}).json()
        metrics = body["decision_metrics"]
        rows.append((item["answerable"], metrics["top_score"], item["q"]))

    rows.sort(key=lambda row: row[1])
    for answerable, score, question in rows:
        print(f"{score:.3f}  {'ANS' if answerable else 'OFF'}  {question}")

    positives = sum(1 for row in rows if row[0])
    negatives = len(rows) - positives
    best = (0.0, 0.0)
    for candidate in sorted({round(row[1], 3) for row in rows}):
        tpr = sum(1 for a, s, _ in rows if a and s >= candidate) / max(1, positives)
        tnr = sum(1 for a, s, _ in rows if not a and s < candidate) / max(1, negatives)
        balanced = (tpr + tnr) / 2
        if balanced > best[0]:
            best = (balanced, candidate)
    off_max = max((s for a, s, _ in rows if not a), default=0.0)
    ans_min = min((s for a, s, _ in rows if a), default=0.0)
    print(f"\nmax off-topic score = {off_max:.3f}, min answerable score = {ans_min:.3f}")
    if ans_min > off_max:
        # Классы разделимы: берем середину зазора, а не его край.
        print(f"recommended threshold = {(ans_min + off_max) / 2:.3f} (classes separable)")
    else:
        print(f"recommended threshold = {best[1]:.3f} (balanced accuracy {best[0]:.2f})")


if __name__ == "__main__":
    main()
