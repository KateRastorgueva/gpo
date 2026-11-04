"""Настройки приложения в админке: форма, сохранение, выгрузка и загрузка YAML."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, require_permission
from app.core.permissions import SETTINGS_MANAGE
from app.services import app_config

router = APIRouter(
    prefix="/admin/settings",
    tags=["admin-settings"],
    dependencies=[Depends(require_permission(SETTINGS_MANAGE))],
)


class SettingsUpdate(BaseModel):
    # None — оставить как есть (так форма шлёт нетронутые поля ключей).
    values: dict[str, Any] = Field(default_factory=dict)
    # Ключи, которые вернуть к значению из .env.
    reset: list[str] = Field(default_factory=list)


class SettingsImport(BaseModel):
    yaml: str = Field(max_length=100_000)


def _validation_error(exc: app_config.SettingsValidationError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"message": "Проверьте значения", "errors": exc.errors},
    )


@router.get("")
def read_settings(session: SessionDep) -> Any:
    return {"groups": app_config.describe(session)}


@router.put("")
def update_settings(session: SessionDep, body: SettingsUpdate) -> Any:
    try:
        changed = app_config.apply_changes(
            session, values=body.values, reset=body.reset
        )
    except app_config.SettingsValidationError as exc:
        raise _validation_error(exc) from exc
    return {"changed": changed, "groups": app_config.describe(session)}


@router.get("/export")
def export_settings(session: SessionDep) -> Response:
    return Response(
        content=app_config.export_yaml(session),
        media_type="application/yaml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ksup-settings.yaml"'},
    )


@router.post("/import")
def import_settings(session: SessionDep, body: SettingsImport) -> Any:
    try:
        result = app_config.import_yaml(session, body.yaml)
    except app_config.SettingsValidationError as exc:
        raise _validation_error(exc) from exc
    return {**result, "groups": app_config.describe(session)}
