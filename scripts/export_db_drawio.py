# ruff: noqa: T201  -- CLI-скрипт, вывод в консоль и есть результат
"""Схема БД проекта в формате draw.io, собранная из моделей SQLModel.

Запуск из каталога backend (нужны переменные окружения проекта, как для бэкенда):
    uv run python ../scripts/export_db_drawio.py ../docs/db-schema.drawio

Таблицы берутся из SQLModel.metadata, поэтому схема всегда совпадает с кодом.
Связь рисуется от строки внешнего ключа к строке первичного ключа целевой
таблицы (ER-стрелка «многие к одному»).
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

from sqlmodel import SQLModel

import app.models  # noqa: F401  -- регистрирует таблицы в metadata

# Колонки слева направо: таблицы, которые чаще связаны, стоят рядом,
# чтобы стрелки шли коротко и не пересекали чужие таблицы.
COLUMNS = [
    ["role", "app_user", "item"],
    ["request_journal", "active_request", "support_feedback"],
    ["answer_journal", "support_ticket"],
    ["knowledge_source", "knowledge_category", "knowledge_archive"],
    ["knowledge_chunk", "knowledge_tag", "tag", "doc_tag", "knowledge_doc"],
]
# Ссылки «кто сделал» на пользователя есть почти у каждой таблицы. Рисуем их
# тонким пунктиром, чтобы они не забивали основные связи.
AUDIT_TARGETS = {"app_user"}
GROUPS = {
    "Пользователи и роли": (["role", "app_user"], "#dae8fc", "#6c8ebf"),
    "Обращения": (
        [
            "request_journal",
            "active_request",
            "answer_journal",
            "support_ticket",
            "support_feedback",
        ],
        "#d5e8d4",
        "#82b366",
    ),
    "База знаний": (
        [
            "knowledge_category",
            "knowledge_source",
            "knowledge_chunk",
            "knowledge_archive",
            "knowledge_doc",
            "tag",
            "knowledge_tag",
            "doc_tag",
        ],
        "#fff2cc",
        "#d6b656",
    ),
    "Остаток шаблона, удалить": (["item"], "#f8cecc", "#b85450"),
}
ROW_H = 22
TABLE_W = 270
GAP_X = 130
GAP_Y = 60
TOP = 90


def column_label(column) -> str:  # type: ignore[no-untyped-def]
    marks = []
    if column.primary_key:
        marks.append("PK")
    if column.foreign_keys:
        marks.append("FK")
    type_cls = type(column.type).__name__.lower()
    if type_cls == "uuid":
        type_name = "uuid"
    else:
        try:
            type_name = str(column.type)
        except Exception:  # noqa: BLE001
            type_name = type_cls
        type_name = type_name.split("(")[0].lower()
    nullable = "" if column.nullable or column.primary_key else " NOT NULL"
    prefix = f"[{', '.join(marks)}] " if marks else ""
    return f"{prefix}{column.name}: {type_name}{nullable}"


def build(path: Path) -> None:
    tables = SQLModel.metadata.tables
    placed = {name for column in COLUMNS for name in column}
    rest = sorted(set(tables) - placed)
    columns = [*COLUMNS, rest] if rest else COLUMNS
    style_of = {
        name: (fill, stroke)
        for names, fill, stroke in GROUPS.values()
        for name in names
    }

    cells: list[str] = []
    row_ids: dict[tuple[str, str], str] = {}
    table_ids: dict[str, str] = {}

    # Легенда групп.
    for i, (title, (_names, fill, stroke)) in enumerate(GROUPS.items()):
        cells.append(
            f'<mxCell id="lg{i}" value="{escape(title)}" '
            f'style="rounded=1;fillColor={fill};strokeColor={stroke};fontSize=12;" '
            f'vertex="1" parent="1"><mxGeometry x="{40 + i * 230}" y="20" '
            f'width="210" height="34" as="geometry"/></mxCell>'
        )

    for ci, names in enumerate(columns):
        x = 40 + ci * (TABLE_W + GAP_X)
        y = TOP
        for name in names:
            if name not in tables:
                continue
            table = tables[name]
            fill, stroke = style_of.get(name, ("#f5f5f5", "#666666"))
            height = ROW_H * (len(table.columns) + 1)
            tid = f"t_{name}"
            table_ids[name] = tid
            cells.append(
                f'<mxCell id="{tid}" value="{escape(name)}" '
                f'style="shape=table;startSize={ROW_H};container=1;collapsible=0;'
                f"childLayout=tableLayout;fixedRows=1;rowLines=0;fontStyle=1;"
                f'align=center;fillColor={fill};strokeColor={stroke};" '
                f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" '
                f'width="{TABLE_W}" height="{height}" as="geometry"/></mxCell>'
            )
            # Порядок строк: первичный ключ, внешние ключи, остальное.
            ordered = sorted(
                table.columns,
                key=lambda c: (0 if c.primary_key else 1 if c.foreign_keys else 2),
            )
            for ri, column in enumerate(ordered):
                rid = f"{tid}_r{ri}"
                row_ids[(name, column.name)] = rid
                font = 1 if column.primary_key else (2 if column.foreign_keys else 0)
                cells.append(
                    f'<mxCell id="{rid}" value="{escape(column_label(column))}" '
                    f'style="shape=partialRectangle;html=1;whiteSpace=wrap;'
                    f"connectable=1;fillColor=none;top=0;left=0;bottom=0;right=0;"
                    f'align=left;spacingLeft=6;fontSize=11;fontStyle={font};" '
                    f'vertex="1" parent="{tid}"><mxGeometry y="{ROW_H * (ri + 1)}" '
                    f'width="{TABLE_W}" height="{ROW_H}" as="geometry"/></mxCell>'
                )
            y += height + GAP_Y

    edge = 0
    for name, table in tables.items():
        for fk in table.foreign_keys:
            target_table = fk.column.table.name
            source = row_ids.get((name, fk.parent.name))
            target = row_ids.get((target_table, fk.column.name))
            if not source or not target:
                continue
            edge += 1
            # Связь внутри одной таблицы (тикет -> переоткрытый тикет) уводим вбок.
            loop = (
                ";exitX=1;exitY=0.5;entryX=1;entryY=0.5" if target_table == name else ""
            )
            if target_table in AUDIT_TARGETS:
                look = "strokeColor=#9aa7b8;dashed=1;opacity=70"
            else:
                look = "strokeColor=#444444;strokeWidth=1.5"
            cells.append(
                f'<mxCell id="e{edge}" style="edgeStyle=entityRelationEdgeStyle;'
                f"endArrow=ERmandOne;startArrow=ERmany;endFill=0;startFill=0;"
                f'{look}{loop};" edge="1" parent="1" '
                f'source="{source}" target="{target}">'
                f'<mxGeometry relative="1" as="geometry"/></mxCell>'
            )

    xml = (
        '<mxfile host="drawio"><diagram name="БД КСУП-2501">'
        '<mxGraphModel grid="1" gridSize="10" page="0"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells)
        + "</root></mxGraphModel></diagram></mxfile>"
    )
    path.write_text(xml, encoding="utf-8")
    print(f"{path}: tables {len(table_ids)}, links {edge}")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "db-schema.drawio"))
