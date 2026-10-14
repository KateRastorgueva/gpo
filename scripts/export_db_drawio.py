# ruff: noqa: T201  -- CLI-скрипт, вывод в консоль и есть результат
"""Схема БД проекта в формате draw.io, собранная из моделей SQLModel.

Запуск из каталога backend (нужны переменные окружения проекта, как для бэкенда):
    uv run python ../scripts/export_db_drawio.py ../docs/db-schema.drawio

Таблицы берутся из SQLModel.metadata, поэтому схема всегда совпадает с кодом.
Связи — внешние ключи (стрелка от таблицы с FK к таблице, на которую он ссылается).
"""

from __future__ import annotations

import sys
from html import escape
from pathlib import Path

from sqlmodel import SQLModel

import app.models  # noqa: F401  -- регистрирует таблицы в metadata

# Группы по смыслу, чтобы на схеме рядом стояло связанное.
GROUPS = [
    ("Пользователи и роли", ["role", "app_user"]),
    (
        "Обращения",
        [
            "active_request",
            "answer_journal",
            "request_journal",
            "support_ticket",
            "support_feedback",
        ],
    ),
    (
        "База знаний",
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
    ),
    ("Остаток шаблона", ["item"]),
]
GROUP_COLORS = ["#dae8fc", "#d5e8d4", "#fff2cc", "#f8cecc"]
ROW_H = 22
TABLE_W = 280
GAP_X = 70
GAP_Y = 50
PER_ROW = 4


def column_label(column) -> str:  # type: ignore[no-untyped-def]
    marks = []
    if column.primary_key:
        marks.append("PK")
    if column.foreign_keys:
        marks.append("FK")
    try:
        type_name = str(column.type)
    except Exception:  # noqa: BLE001
        type_name = type(column.type).__name__
    type_name = type_name.split("(")[0].lower()
    nullable = "" if column.nullable or column.primary_key else " NOT NULL"
    prefix = f"[{', '.join(marks)}] " if marks else ""
    return f"{prefix}{column.name}: {type_name}{nullable}"


def build(path: Path) -> None:
    tables = SQLModel.metadata.tables
    known = {name for _, names in GROUPS for name in names}
    rest = sorted(set(tables) - known)
    groups = [*GROUPS, ("Прочее", rest)] if rest else GROUPS

    cells: list[str] = []
    ids: dict[str, str] = {}
    y = 40
    for gi, (title, names) in enumerate(groups):
        names = [n for n in names if n in tables]
        if not names:
            continue
        color = GROUP_COLORS[gi % len(GROUP_COLORS)]
        cells.append(
            f'<mxCell id="g{gi}" value="{escape(title)}" style="text;fontSize=18;fontStyle=1;" '
            f'vertex="1" parent="1"><mxGeometry x="40" y="{y}" width="600" height="30" as="geometry"/></mxCell>'
        )
        y += 40
        row_height = 0
        for i, name in enumerate(names):
            table = tables[name]
            col = i % PER_ROW
            if col == 0 and i:
                y += row_height + GAP_Y
                row_height = 0
            x = 40 + col * (TABLE_W + GAP_X)
            height = ROW_H * (len(table.columns) + 1) + 6
            row_height = max(row_height, height)
            tid = f"t_{name}"
            ids[name] = tid
            cells.append(
                f'<mxCell id="{tid}" value="{escape(name)}" '
                f'style="swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;startSize={ROW_H};'
                f'horizontalStack=0;resizeParent=1;collapsible=1;fillColor={color};" '
                f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{TABLE_W}" height="{height}" as="geometry"/></mxCell>'
            )
            for ci, column in enumerate(table.columns):
                style = (
                    "text;align=left;verticalAlign=middle;spacingLeft=6;fontSize=11;"
                )
                if column.primary_key:
                    style += "fontStyle=1;"
                elif column.foreign_keys:
                    style += "fontStyle=2;"
                cells.append(
                    f'<mxCell id="{tid}_c{ci}" value="{escape(column_label(column))}" style="{style}" '
                    f'vertex="1" parent="{tid}"><mxGeometry y="{ROW_H * (ci + 1)}" width="{TABLE_W}" '
                    f'height="{ROW_H}" as="geometry"/></mxCell>'
                )
        y += row_height + GAP_Y + 20

    edge = 0
    for name, table in tables.items():
        for fk in table.foreign_keys:
            target = fk.column.table.name
            if name not in ids or target not in ids:
                continue
            edge += 1
            label = escape(fk.parent.name)
            cells.append(
                f'<mxCell id="e{edge}" value="{label}" '
                f'style="edgeStyle=orthogonalEdgeStyle;rounded=1;endArrow=ERmandOne;startArrow=ERmany;'
                f'fontSize=9;strokeColor=#6c8ebf;" edge="1" parent="1" source="{ids[name]}" target="{ids[target]}">'
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
    print(f"{path}: таблиц {len(ids)}, связей {edge}")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "db-schema.drawio"))
