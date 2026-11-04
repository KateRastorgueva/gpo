import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import event_log
from app.core.config import settings


@pytest.fixture()
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "EVENT_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "EVENT_LOG_ENABLED", True)
    return tmp_path


def _lines(log_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(log_dir.glob("events-*.jsonl")):
        records += [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    return records


def test_log_event_writes_json_line(log_dir: Path) -> None:
    event_log.log_event("test.event", value=1, skipped=None, text="x" * 2000)

    [record] = _lines(log_dir)
    assert record["event"] == "test.event"
    assert record["value"] == 1
    assert "skipped" not in record
    assert len(record["text"]) <= event_log.MAX_TEXT + 1


def test_log_event_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    monkeypatch.setattr(settings, "EVENT_LOG_DIR", str(blocker / "sub"))

    event_log.log_event("test.event")  # не должно бросать исключение


def test_read_events_filters_by_prefix_and_since(log_dir: Path) -> None:  # noqa: ARG001
    event_log.log_event("support.ask", mode="faq")
    event_log.log_event("http.request", status=200, duration_ms=5)

    assert [e["event"] for e in event_log.read_events(event_prefix="support.")] == [
        "support.ask"
    ]
    future = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert event_log.read_events(since=future) == []


def test_cleanup_removes_only_old_files(log_dir: Path) -> None:
    old = log_dir / "events-2000-01-01.jsonl"
    old.write_text("{}\n")
    event_log.log_event("fresh")

    assert event_log.cleanup_old_files(retention_days=30) == 1
    assert not old.exists()
    assert len(list(log_dir.glob("events-*.jsonl"))) == 1


def test_summarize_counts_modes_and_errors() -> None:
    events = [
        {"event": "http.request", "status": 200, "duration_ms": 10, "route": "/a"},
        {"event": "http.request", "status": 500, "duration_ms": 90, "route": "/b"},
        {
            "event": "support.ask",
            "mode": "faq",
            "provider": "faq",
            "response_time_ms": 3,
        },
        {
            "event": "support.ask",
            "mode": "operator",
            "provider": "gemini_file_search",
            "escalated": True,
            "response_time_ms": 900,
        },
        {"event": "rag.provider_error", "error": "boom"},
    ]

    summary = event_log.summarize(events)

    assert summary["http"]["by_status"] == {"2xx": 1, "5xx": 1}
    assert summary["http"]["slowest_routes"][0]["route"] == "/b"
    assert summary["support"]["by_mode"] == {"faq": 1, "operator": 1}
    assert summary["support"]["escalation_rate"] == 0.5
    assert summary["errors"]["by_event"] == {"rag.provider_error": 1}


def test_api_requests_and_answers_are_logged(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    log_dir: Path,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/support/ask",
        headers=superuser_token_headers,
        json={"question": "Где посмотреть расписание занятий?", "channel": "web"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")

    events = _lines(log_dir)
    [ask] = [e for e in events if e["event"] == "support.ask"]
    assert ask["request_id"] == response.json()["request_id"]
    assert ask["mode"] == response.json()["mode"]
    assert "response_time_ms" in ask
    http = [e for e in events if e["event"] == "http.request"]
    assert any(e["route"].endswith("/support/ask") and e["status"] == 200 for e in http)
    # Токен в журнал не попадает: только признак, что заголовок был.
    assert all("Bearer" not in json.dumps(e) for e in http)

    summary = client.get(
        f"{settings.API_V1_STR}/admin/logs/summary", headers=superuser_token_headers
    )
    assert summary.status_code == 200
    assert summary.json()["support"]["asks"] >= 1

    listed = client.get(
        f"{settings.API_V1_STR}/admin/logs/events",
        headers=superuser_token_headers,
        params={"event": "support."},
    )
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    download = client.get(
        f"{settings.API_V1_STR}/admin/logs/files/{day}", headers=superuser_token_headers
    )
    assert download.status_code == 200
    assert b"support.ask" in download.content


def test_logs_api_requires_metrics_permission(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/admin/logs/summary", headers=normal_user_token_headers
    )
    assert response.status_code == 403
