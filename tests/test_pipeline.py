import zipfile

import pytest

from news_intel import exports, pipeline, prompts, providers, sources
from news_intel.core import config, db


def validation_values(validation):
    return validation.formula1.strip('"').split(",")


def article(url="https://example.test/1"):
    return sources.RawArticle(
        source="khabarfoori", url=url, title="حمله و تاثیر بر طلا",
        lead="خبر امنیتی اقتصادی", content="جزئیات خبر",
        original_outlet="ایسنا", published_at="2026-08-16T10:00:00+03:30",
    )


def test_process_is_idempotent_and_retains_unassessed_axes(conn):
    provider = providers.RuleProvider()
    first = pipeline.process(conn, [article()], provider, run_id="run1")
    second = pipeline.process(conn, [article()], provider, run_id="run2")
    evaluation = conn.execute("SELECT * FROM evaluations").fetchone()
    assert first == {"fetched": 1, "new": 1, "rejected": 0, "duplicate": 0,
                     "classified": 1, "evaluated": 1, "summarized": 1}
    assert second == {"fetched": 1, "new": 0, "rejected": 0, "duplicate": 0,
                      "classified": 0, "evaluated": 0, "summarized": 0}
    assert evaluation["gold_price_impact"] == "زیاد"
    assert evaluation["security_relevance"] == "زیاد"


def test_export_preserves_the_workbook_template(tmp_path):
    path = tmp_path / "news.db"
    from news_intel.core import db

    with db.init_db(path) as conn:
        pipeline.process(conn, [article()], providers.RuleProvider(), run_id="run")
        result = exports.export_all(conn, tmp_path / "out")
    assert all(path.exists() for path in result.values())
    workbook_path = next(path for name, path in result.items() if name.startswith("excel:"))
    from openpyxl import load_workbook
    template = load_workbook(config.WORKBOOK_TEMPLATE_PATH)
    workbook = load_workbook(workbook_path, data_only=False)
    sheet = workbook["بررسی خبر"]

    # The daily file is the single operational sheet, matching every workbook the team
    # produced. The template's reference sheets stay in the template.
    assert workbook.sheetnames == ["بررسی خبر"]
    assert sheet["A2"].style_id == template["بررسی خبر"]["A2"].style_id
    assert str(sheet["J3"].value).startswith("=IF(")

    # The template's own header row leaves L2 blank; the export has to supply it or the
    # link column ships unlabelled, as it did in every legacy workbook.
    assert [sheet.cell(2, column).value for column in range(1, 13)] == exports.HEADERS

    trend = next(
        validation for validation in sheet.data_validations.dataValidation
        if validation.formula1.startswith('"↑')
    )
    assert validation_values(trend) == list(prompts.GOLD_TRENDS)
    levels = next(
        validation for validation in sheet.data_validations.dataValidation
        if validation is not trend
    )
    assert validation_values(levels) == list(db.LEVELS), "score columns are ordinal, not yes/no"
    with zipfile.ZipFile(config.WORKBOOK_TEMPLATE_PATH) as source, zipfile.ZipFile(workbook_path) as output:
        template_xml = source.read("xl/worksheets/sheet1.xml")
        output_xml = output.read("xl/worksheets/sheet1.xml")
    template_extension = template_xml[template_xml.find(b"<extLst"):template_xml.find(b"</extLst>") + len(b"</extLst>")]
    output_extension = output_xml[output_xml.find(b"<extLst"):output_xml.find(b"</extLst>") + len(b"</extLst>")]
    assert output_extension == template_extension
