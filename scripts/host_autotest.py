# -*- coding: utf-8 -*-
"""Автотест командного хоста: прогоняет основные сценарии и сохраняет отчёт с логами.

Что проверяет (только чтение и вопросы в чат, ничего не удаляет):
  1. фронтенд отдаёт страницу, backend отвечает на health-check;
  2. вход администратора и /users/me;
  3. выбранный RAG-движок (если на хосте есть вкладка «Движки RAG»);
  4. вопросы из scripts/host_autotest.json: режим ответа (faq/rag/operator),
     уверенность, время, источники — сравнивает с ожиданием;
  5. история чата и метрики админки;
  6. журнал событий хоста за время прогона: /admin/logs/events и /admin/logs/summary.

Результат — папка reports/host/<UTC-время>/ с файлами report.md, results.json,
events.jsonl, summary.json. С флагом --push отчёт коммитится в отдельную ветку
``host-reports`` (через временный git worktree, ваша текущая ветка не трогается)
и отправляется на GitHub.

Нужен только Python 3.10+ без сторонних пакетов. Запуск из корня репозитория:

    python scripts/host_autotest.py                       # хост из HOST_URL или по умолчанию
    python scripts/host_autotest.py --base-url http://localhost:5173 --push
    python scripts/host_autotest.py --skip-questions      # без расхода квоты движка

Логин и пароль берутся из FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD (окружение
или файл .env в корне репозитория). Пароль в отчёт не попадает.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://lrahpg-92-126-5-168.a.2na.am"
DEFAULT_SCENARIOS = ROOT / "scripts" / "host_autotest.json"
DEFAULT_OUT = ROOT / "reports" / "host"
REPORT_BRANCH = "host-reports"
API = "/api/v1"


# --------------------------------------------------------------------------- utils


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass
class HttpResult:
    status: int
    ms: int
    body: Any
    headers: dict[str, str]
    error: str | None = None


class Client:
    def __init__(self, base_url: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        form: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        raw: bool = False,
    ) -> HttpResult:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        data: bytes | None = None
        headers = {"Accept": "application/json", "User-Agent": "host-autotest/1"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                status = resp.status
                resp_headers = dict(resp.headers.items())
            error = None
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            resp_headers = dict(exc.headers.items()) if exc.headers else {}
            error = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 — сеть/таймаут попадают в отчёт
            return HttpResult(0, _ms(started), None, {}, f"{type(exc).__name__}: {exc}")
        body: Any = payload
        if not raw:
            text = payload.decode("utf-8", errors="replace")
            try:
                body = json.loads(text) if text else None
            except json.JSONDecodeError:
                body = text
        return HttpResult(status, _ms(started), body, resp_headers, error)


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@dataclass
class Check:
    name: str
    ok: bool
    ms: int | None = None
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- checks


def run_checks(args: argparse.Namespace) -> tuple[list[Check], dict[str, Any]]:
    client = Client(args.base_url, args.timeout)
    checks: list[Check] = []
    context: dict[str, Any] = {"base_url": args.base_url}

    front = client.request("GET", "/", raw=True)
    html = (
        front.body.decode("utf-8", "replace") if isinstance(front.body, bytes) else ""
    )
    checks.append(
        Check(
            "frontend: главная страница",
            front.status == 200 and 'id="root"' in html,
            front.ms,
            front.error or f"HTTP {front.status}",
        )
    )

    health = client.request("GET", f"{API}/utils/health-check/")
    checks.append(
        Check(
            "backend: health-check",
            health.status == 200 and health.body is True,
            health.ms,
            health.error or f"HTTP {health.status}",
        )
    )

    login = client.request(
        "POST",
        f"{API}/login/access-token",
        form={"username": args.username, "password": args.password},
    )
    token = login.body.get("access_token") if isinstance(login.body, dict) else None
    checks.append(
        Check(
            "вход администратора",
            bool(token),
            login.ms,
            login.error or ("ok" if token else "нет access_token"),
        )
    )
    if not token:
        return checks, context
    client.token = token

    me = client.request("GET", f"{API}/users/me")
    checks.append(
        Check(
            "/users/me",
            me.status == 200,
            me.ms,
            me.error or (me.body.get("email", "") if isinstance(me.body, dict) else ""),
        )
    )

    provider = client.request("GET", f"{API}/admin/rag/provider")
    if provider.status == 200 and isinstance(provider.body, dict):
        context["rag_provider"] = provider.body
        checks.append(
            Check(
                "RAG: выбранный движок",
                True,
                provider.ms,
                str(provider.body.get("active")),
            )
        )
    else:
        checks.append(
            Check(
                "RAG: выбранный движок",
                provider.status == 404,  # старая версия хоста без вкладки — не ошибка
                provider.ms,
                f"нет эндпоинта /admin/rag/provider (HTTP {provider.status})",
            )
        )

    session_id = f"autotest-{context.setdefault('run_id', args.run_id)}"
    if not args.skip_questions:
        scenarios = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
        for scenario in scenarios["scenarios"]:
            checks.append(ask(client, scenario, session_id))

    history = client.request(
        "GET", f"{API}/support/history", params={"session_id": session_id, "limit": 50}
    )
    count = history.body.get("count") if isinstance(history.body, dict) else None
    expected = (
        0
        if args.skip_questions
        else len([c for c in checks if c.name.startswith("вопрос:")])
    )
    checks.append(
        Check(
            "история чата прогона",
            history.status == 200 and (count or 0) >= expected,
            history.ms,
            history.error or f"записей: {count}, ожидалось ≥ {expected}",
        )
    )

    metrics = client.request("GET", f"{API}/admin/metrics")
    checks.append(
        Check(
            "метрики админки",
            metrics.status == 200,
            metrics.ms,
            metrics.error or "ok",
            data=metrics.body if isinstance(metrics.body, dict) else {},
        )
    )

    # Журнал хоста: всё, что backend записал с начала прогона.
    since = args.started_at.isoformat()
    events = client.request(
        "GET",
        f"{API}/admin/logs/events",
        params={"since": since, "limit": 5000},
    )
    summary = client.request(
        "GET", f"{API}/admin/logs/summary", params={"since": since}
    )
    logs_ok = events.status == 200 and isinstance(events.body, dict)
    context["events"] = events.body.get("data", []) if logs_ok else []
    context["summary"] = summary.body if summary.status == 200 else None
    checks.append(
        Check(
            "журнал событий хоста",
            logs_ok and len(context["events"]) > 0,
            events.ms,
            f"событий: {len(context['events'])}"
            if logs_ok
            else f"нет /admin/logs (HTTP {events.status}) — хост на старой версии",
        )
    )
    if args.full_day and logs_ok:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        full = client.request("GET", f"{API}/admin/logs/files/{day}", raw=True)
        if full.status == 200 and isinstance(full.body, bytes):
            context["full_day"] = (day, full.body)
    return checks, context


def ask(client: Client, scenario: dict[str, Any], session_id: str) -> Check:
    result = client.request(
        "POST",
        f"{API}/support/ask",
        json_body={"question": scenario["question"], "session_id": session_id},
    )
    name = f"вопрос: {scenario['id']}"
    if result.status != 200 or not isinstance(result.body, dict):
        return Check(name, False, result.ms, result.error or f"HTTP {result.status}")
    body = result.body
    mode = body.get("mode")
    titles = [str(s.get("source_title", "")) for s in body.get("sources", [])]
    problems = []
    expect_mode = scenario.get("expect_mode", "any")
    if expect_mode != "any" and mode != expect_mode:
        problems.append(f"режим {mode}, ожидался {expect_mode}")
    expect_source = scenario.get("expect_source")
    if expect_source and mode == "rag" and not any(expect_source in t for t in titles):
        problems.append(f"нет источника «{expect_source}»")
    return Check(
        name,
        not problems,
        result.ms,
        "; ".join(problems) or f"{mode}, уверенность {body.get('confidence')}",
        data={
            "question": scenario["question"],
            "mode": mode,
            "confidence": body.get("confidence"),
            "route_reason": body.get("route_reason"),
            "escalated": body.get("escalated"),
            "sources": titles[:5],
            "answer_preview": str(body.get("answer", ""))[:300],
            "request_id": body.get("request_id"),
            "x_request_id": result.headers.get("X-Request-ID")
            or result.headers.get("x-request-id"),
        },
    )


# --------------------------------------------------------------------------- report


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def write_report(
    out_dir: Path,
    args: argparse.Namespace,
    checks: list[Check],
    context: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    passed = sum(c.ok for c in checks)
    try:
        local_commit = git("rev-parse", "--short", "HEAD", check=False)
        local_branch = git("rev-parse", "--abbrev-ref", "HEAD", check=False)
    except FileNotFoundError:
        local_commit = local_branch = "?"
    meta = {
        "run_id": args.run_id,
        "started_at": args.started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "passed": passed,
        "total": len(checks),
        "runner_branch": local_branch,
        "runner_commit": local_commit,
        "rag_provider": context.get("rag_provider"),
    }
    (out_dir / "results.json").write_text(
        json.dumps(
            {"meta": meta, "checks": [asdict(c) for c in checks]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with (out_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
        for event in context.get("events", []):
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    if context.get("summary") is not None:
        (out_dir / "summary.json").write_text(
            json.dumps(context["summary"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if context.get("full_day"):
        day, data = context["full_day"]
        (out_dir / f"events-{day}-full.jsonl").write_bytes(data)

    lines = [
        f"# Автотест хоста {args.run_id}",
        "",
        f"- Хост: {args.base_url}",
        f"- Итог: **{passed} из {len(checks)}** проверок прошли",
        f"- Движок RAG: {(context.get('rag_provider') or {}).get('active', 'не известно')}",
        f"- Запускал из ветки `{local_branch}` ({local_commit})",
        "",
        "| Проверка | Итог | мс | Подробности |",
        "|---|---|---|---|",
    ]
    for c in checks:
        detail = str(c.detail).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {c.name} | {'✅' if c.ok else '❌'} | {c.ms or ''} | {detail} |"
        )

    asks = [c for c in checks if c.name.startswith("вопрос:") and c.data]
    if asks:
        lines += ["", "## Ответы", ""]
        for c in asks:
            d = c.data
            lines += [
                f"### {c.name[len('вопрос: ') :]}",
                "",
                f"- Вопрос: {d['question']}",
                f"- Режим: `{d['mode']}` ({d['route_reason']}), уверенность {d['confidence']}, {c.ms} мс",
                f"- Источники: {', '.join(d['sources']) or 'нет'}",
                f"- Ответ: {d['answer_preview']}",
                "",
            ]
    summary = context.get("summary")
    if summary:
        http = summary.get("http", {})
        support = summary.get("support", {})
        lines += [
            "## Журнал хоста за прогон",
            "",
            f"- Событий: {summary.get('events')}, HTTP-запросов: {http.get('requests')}"
            f" ({http.get('by_status')}), p50 {http.get('p50_ms')} мс, p95 {http.get('p95_ms')} мс",
            f"- Ответы: {support.get('by_mode')}, движки {support.get('by_provider')},"
            f" эскалаций {support.get('escalation_rate')}",
            f"- Ошибки: {summary.get('errors')}",
            "",
            "Полный журнал прогона: `events.jsonl`, сводка: `summary.json`.",
        ]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def push_report(
    out_dir: Path, args: argparse.Namespace, passed: int, total: int
) -> None:
    """Коммитит папку отчёта в ветку host-reports через временный worktree."""

    remote_exists = bool(
        git("ls-remote", "--heads", "origin", REPORT_BRANCH, check=False)
    )
    worktree = Path(tempfile.mkdtemp(prefix="host-reports-"))
    shutil.rmtree(worktree)
    try:
        if remote_exists:
            git("fetch", "origin", REPORT_BRANCH)
            git(
                "worktree",
                "add",
                "-B",
                REPORT_BRANCH,
                str(worktree),
                f"origin/{REPORT_BRANCH}",
            )
        else:
            git("worktree", "add", "--detach", str(worktree))
            git("checkout", "--orphan", REPORT_BRANCH, cwd=worktree)
            git("rm", "-rf", "--quiet", "--ignore-unmatch", ".", cwd=worktree)
            (worktree / "README.md").write_text(
                "# Отчёты автотеста хоста\n\nКаждая папка — один прогон "
                "`scripts/host_autotest.py` (report.md, results.json, events.jsonl).\n",
                encoding="utf-8",
            )
        target = worktree / out_dir.name
        shutil.copytree(out_dir, target, dirs_exist_ok=True)
        git("add", "-A", cwd=worktree)
        git(
            "commit",
            "-m",
            f"report: host autotest {args.run_id} ({passed}/{total})",
            cwd=worktree,
        )
        git("push", "-u", "origin", REPORT_BRANCH, cwd=worktree)
        print(f"Отчёт отправлен в ветку {REPORT_BRANCH}: {out_dir.name}/")
    finally:
        git("worktree", "remove", "--force", str(worktree), check=False)


# --------------------------------------------------------------------------- main


def parse_args() -> argparse.Namespace:
    env = {**read_dotenv(ROOT / ".env"), **os.environ}
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default=env.get("HOST_URL", DEFAULT_BASE_URL))
    parser.add_argument("--username", default=env.get("FIRST_SUPERUSER"))
    parser.add_argument("--password", default=env.get("FIRST_SUPERUSER_PASSWORD"))
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--skip-questions", action="store_true", help="не задавать вопросы (без квоты)"
    )
    parser.add_argument(
        "--full-day", action="store_true", help="приложить весь журнал хоста за сегодня"
    )
    parser.add_argument(
        "--push", action="store_true", help=f"закоммитить отчёт в ветку {REPORT_BRANCH}"
    )
    args = parser.parse_args()
    if not args.username or not args.password:
        parser.error("нужны FIRST_SUPERUSER и FIRST_SUPERUSER_PASSWORD (env или .env)")
    args.started_at = datetime.now(timezone.utc)
    args.run_id = args.started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    return args


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows
    args = parse_args()
    checks, context = run_checks(args)
    out_dir = Path(args.out) / args.run_id
    write_report(out_dir, args, checks, context)
    passed = sum(c.ok for c in checks)
    for c in checks:
        print(f"{'OK  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    print(f"\n{passed}/{len(checks)} — отчёт: {out_dir / 'report.md'}")
    if args.push:
        push_report(out_dir, args, passed, len(checks))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
