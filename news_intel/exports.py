"""Template-preserving exports for the operational workbook and text feeds."""

from __future__ import annotations

import shutil
import sqlite3
import warnings
import zipfile
import re
from copy import copy
from datetime import time
from pathlib import Path

import jdatetime
from openpyxl import load_workbook

from .core import config
from .core.db import LEVELS
from .core.scoring import NOTIFY, decide
from .prompts import GOLD_TRENDS

HEADERS = [
    "شناسه خبر", "تاریخ انتشار", "ساعت انتشار", "منبع", "تیتر خبر",
    "اطمینان از وقوع خبر", "چقدر بر تغییر قیمت طلا اثر دارد؟",
    "چقدربا امنیت مرتبط است ؟", "جهت طلا", "وضعیت اطلاع رسانی", "توضیحات", "لینک",
]
SHEET = "بررسی خبر"
# The template pre-styles rows to here; dropdowns should cover the same span.
MAX_STYLED_ROW = 504


def _persian_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        year, month, day = map(int, value.replace("/", "-").split("-"))
        return f"{day} {jdatetime.date.j_months_fa[month - 1]} {year}"
    except (ValueError, IndexError):
        return value


def workbook_filename(day: str) -> str:
    """Daily workbook name in the convention the team already files by.

    Legacy wrote "ثبت و تحلیل خبر - 1 اردیبهشت 1405.xlsx"; an ISO date here would land
    the same content under names nobody recognises. Reuses _persian_date rather than
    repeating the month lookup.
    """
    return f"ثبت و تحلیل خبر - {_persian_date(day) or day}.xlsx"


def _time(value: str | None) -> time | str:
    if not value:
        return ""
    try:
        hour, minute = map(int, value.split(":")[:2])
        return time(hour, minute)
    except ValueError:
        return value


def rows(conn: sqlite3.Connection) -> list[dict[str, str]]:
    query = """
    SELECT a.*, c.category, e.confidence_occurrence, e.gold_price_impact,
           e.security_relevance, e.gold_trend, s.optimized_title, s.one_line
    FROM articles a
    LEFT JOIN latest_classification c ON c.article_id=a.id
    LEFT JOIN latest_evaluation e ON e.article_id=a.id
    LEFT JOIN latest_summary s ON s.article_id=a.id
    WHERE a.duplicate_of IS NULL
    ORDER BY COALESCE(a.published_at_gregorian, a.fetched_at), a.url
    """
    result = []
    for index, row in enumerate(conn.execute(query), 1):
        decision = decide(row["confidence_occurrence"], row["gold_price_impact"], row["security_relevance"])
        result.append({
            "_day": row["published_at_persian"] or "",
            "_category": row["category"] or "other",
            "شناسه خبر": str(index),
            "تاریخ انتشار": _persian_date(row["published_at_persian"]),
            "ساعت انتشار": row["published_time"] or "",
            "منبع": row["original_outlet"] or row["source"],
            "تیتر خبر": row["optimized_title"] or row["original_title"],
            "اطمینان از وقوع خبر": row["confidence_occurrence"] or "",
            "چقدر بر تغییر قیمت طلا اثر دارد؟": row["gold_price_impact"] or "",
            "چقدربا امنیت مرتبط است ؟": row["security_relevance"] or "",
            "جهت طلا": row["gold_trend"] or "",
            "وضعیت اطلاع رسانی": decision.status,
            "توضیحات": row["one_line"] or "",
            "لینک": row["url"],
        })
    return result


def _formula(row: int) -> str:
    metrics = f"F{row}:H{row}"
    return (
        f'=IF(AND(COUNTIF({metrics},"زیاد")+COUNTIF({metrics},"خیلی زیاد")>=2,'
        f'COUNTIF({metrics},"خیلی کم")=0),"اطلاع‌رسانی شود","اطلاع‌رسانی نشود")'
    )


def _load_template():
    if not config.WORKBOOK_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"missing workbook template: {config.WORKBOOK_TEMPLATE_PATH}")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r".*extension is not supported.*", category=UserWarning)
        return load_workbook(config.WORKBOOK_TEMPLATE_PATH)


def _template_extensions(path: Path) -> bytes | None:
    with zipfile.ZipFile(config.WORKBOOK_TEMPLATE_PATH) as source:
        xml = source.read("xl/worksheets/sheet1.xml")
    start = xml.find(b"<extLst")
    end = xml.find(b"</extLst>", start)
    return xml[start:end + len(b"</extLst>")] if start >= 0 and end >= 0 else None


def _restore_template_extensions(path: Path) -> None:
    extension = _template_extensions(path)
    if not extension:
        return
    with zipfile.ZipFile(path) as source:
        payload = {entry.filename: source.read(entry.filename) for entry in source.infolist()}
    xml = payload["xl/worksheets/sheet1.xml"]
    with zipfile.ZipFile(config.WORKBOOK_TEMPLATE_PATH) as source:
        template_xml = source.read("xl/worksheets/sheet1.xml")
    template_root_start = template_xml.find(b"<worksheet")
    template_root_end = template_xml.find(b">", template_root_start) + 1
    output_root_start = xml.find(b"<worksheet")
    output_root_end = xml.find(b">", output_root_start)
    template_root = template_xml[template_root_start:template_root_end]
    output_root = xml[output_root_start:output_root_end]
    namespaces = re.findall(rb'\s(xmlns(?::[A-Za-z0-9]+)?="[^"]+")', template_root)
    missing = [item for item in namespaces if item.split(b"=", 1)[0] not in output_root]
    if missing:
        xml = xml[:output_root_end] + b" " + b" ".join(missing) + xml[output_root_end:]
    start = xml.find(b"<extLst")
    end = xml.find(b"</extLst>", start)
    if start >= 0 and end >= 0:
        xml = xml[:start] + xml[end + len(b"</extLst>"):]
    payload["xl/worksheets/sheet1.xml"] = xml.replace(b"</worksheet>", extension + b"</worksheet>")
    temporary = path.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        for name, content in payload.items():
            target.writestr(name, content)
    temporary.replace(path)


def _fix_validations(sheet) -> None:
    """Point the template's dropdowns at the values this pipeline actually writes.

    The template carries two stale ones: the score columns get a «بله,خیر» (yes/no) list
    from row 304 down, which is not the ordinal scale those columns hold, and the gold
    trend list stops at row 303. Left alone, an analyst clicking a dropdown past row 303
    is offered answers that do not belong in that column.
    """
    from openpyxl.worksheet.datavalidation import DataValidation

    sheet.data_validations.dataValidation = []
    levels = DataValidation(type="list", formula1=f'"{",".join(LEVELS)}"', allow_blank=True)
    trend = DataValidation(type="list", formula1=f'"{",".join(GOLD_TRENDS)}"', allow_blank=True)
    sheet.add_data_validation(levels)
    sheet.add_data_validation(trend)
    levels.add(f"F3:H{MAX_STYLED_ROW}")
    trend.add(f"I3:I{MAX_STYLED_ROW}")


def _copy_row_style(sheet, source: int, target: int) -> None:
    for column in range(1, 13):
        origin, destination = sheet.cell(source, column), sheet.cell(target, column)
        destination._style = copy(origin._style)
        destination.number_format = origin.number_format
        destination.protection = copy(origin.protection)
        destination.alignment = copy(origin.alignment)
        destination.fill = copy(origin.fill)
        destination.font = copy(origin.font)
        destination.border = copy(origin.border)
    sheet.row_dimensions[target].height = sheet.row_dimensions[source].height


def build_workbook(records: list[dict[str, str]], target: Path) -> Path:
    """Clone the template into a daily workbook, preserving its styling.

    The template is the analyst's own source file: four sheets, and reference material
    (keyword taxonomy, source register) alongside the operational one. The daily output
    is not that file. All 40 workbooks the team actually produced carry a single sheet,
    so the auxiliary ones are dropped here rather than shipped every day - they stay in
    the template, which is where that reference material belongs.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.WORKBOOK_TEMPLATE_PATH, target)
    workbook = _load_template() if target == config.WORKBOOK_TEMPLATE_PATH else load_workbook(target)
    for name in list(workbook.sheetnames):
        if name != SHEET:
            del workbook[name]
    sheet = workbook[SHEET]
    # The template's own header row is missing this one cell, so every workbook the
    # legacy exporter produced from it had an unlabelled link column.
    sheet.cell(2, 12).value = HEADERS[11]
    _fix_validations(sheet)
    existing_end = max(sheet.max_row, 3)
    for row in range(3, existing_end + 1):
        for column in range(1, 13):
            cell = sheet.cell(row, column)
            cell.value = None
            cell.hyperlink = None
    for index, record in enumerate(records, 3):
        if index > existing_end:
            _copy_row_style(sheet, 3, index)
        for column, header in enumerate(HEADERS, 1):
            cell = sheet.cell(index, column)
            value = record[header]
            if header == "ساعت انتشار":
                value = _time(value)
            if header == "وضعیت اطلاع رسانی":
                value = _formula(index)
            cell.value = value
            if header == "لینک" and value:
                cell.hyperlink = value
    workbook.save(target)
    workbook.close()
    _restore_template_extensions(target)
    return target


def _text(records: list[dict[str, str]]) -> str:
    return "\n\n".join(
        f"{record['تیتر خبر']}\n\n{record['توضیحات']}\n\n"
        f"{record['منبع']} | {record['تاریخ انتشار']} | {record['ساعت انتشار']}\n"
        + "-" * 50
        for record in records
    ) + ("\n" if records else "")


def export_all(conn: sqlite3.Connection, directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    records = rows(conn)
    eligible = [row for row in records if row["_category"] != "other"]
    # Filenames follow the legacy convention the team already files by:
    # "ثبت و تحلیل خبر - 1 اردیبهشت 1405.xlsx", not an ISO date.
    by_day: dict[str, list[dict[str, str]]] = {}
    for record in eligible:
        if record["_day"]:
            by_day.setdefault(record["_day"], []).append(record)
    files: dict[str, Path] = {}
    excel_dir = directory / "Excel Files"
    for day, day_rows in by_day.items():
        files[f"excel:{day}"] = build_workbook(day_rows, excel_dir / workbook_filename(day))
    important = [row for row in eligible if row["وضعیت اطلاع رسانی"] == NOTIFY]
    files["important"] = directory / "important_news.txt"
    files["important"].write_text(_text(important), encoding="utf-8")
    for category in ("security", "economics", "security/economics", "other"):
        path = directory / "TXT Files" / f"{category.replace('/', '_')}_news.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_text([row for row in records if row["_category"] == category]), encoding="utf-8")
        files[f"text:{category}"] = path
    return files
