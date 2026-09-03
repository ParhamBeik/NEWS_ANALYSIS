"""The analyst workbook.

The tests that matter here are the ones about the template's own quirks. A workbook with
the wrong dropdown values or a missing extLst block still OPENS - which is precisely why
those failures went unnoticed in the legacy exporter for 40 files.
"""

from __future__ import annotations

import itertools
import zipfile

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from core.scoring import HIGH_COUNT_REQUIRED, decide
from core.vocabulary import GOLD_TRENDS, LEVELS, NotifyStatus
from exports import workbook
from inference.models import Classification, Evaluation, Summary

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
def analysed(make_article, variant):
    """An article with a full set of inference rows, as the workbook expects."""

    def _make(category="security", **scores):
        article = make_article(published_at=timezone.now())
        Classification.objects.create(
            article=article, variant=variant, prompt_version=variant.prompt_version,
            provider="gapgpt", model="m", category=category, confidence="زیاد",
        )
        Evaluation.objects.create(
            article=article, variant=variant, prompt_version=variant.prompt_version,
            provider="gapgpt", model="m",
            confidence_occurrence=scores.get("confidence_occurrence", "زیاد"),
            gold_price_impact=scores.get("gold_price_impact"),
            security_relevance=scores.get("security_relevance", "زیاد"),
            gold_trend=scores.get("gold_trend", "↑"),
        )
        Summary.objects.create(
            article=article, variant=variant, prompt_version=variant.prompt_version,
            provider="gapgpt", model="m",
            optimized_title="تیتر بهینه‌شده", one_line="خلاصه یک‌خطی",
        )
        return article

    return _make


class TestRows:
    def test_uses_the_optimised_title_when_available(self, analysed):
        analysed()
        assert workbook.rows()[0]["تیتر خبر"] == "تیتر بهینه‌شده"

    def test_falls_back_to_the_original_title(self, make_article):
        article = make_article(published_at=timezone.now())
        assert workbook.rows()[0]["تیتر خبر"] == article.original_title

    def test_an_unassessed_axis_is_blank_not_a_level(self, analysed):
        """The workbook has to show 'nobody judged this', and a blank cell is how the
        team's file expresses it. Writing a level would be the sentinel bug in Excel."""
        analysed(gold_price_impact=None)
        record = workbook.rows()[0]
        assert record["چقدر بر تغییر قیمت طلا اثر دارد؟"] == ""

    def test_notify_status_matches_the_scoring_rule(self, analysed):
        analysed(confidence_occurrence="زیاد", security_relevance="زیاد")
        assert workbook.rows()[0][workbook.NOTIFY_HEADER] == NotifyStatus.NOTIFY

    def test_duplicates_are_excluded(self, analysed, make_article):
        canonical = analysed()
        duplicate = make_article(published_at=timezone.now())
        duplicate.duplicate_of = canonical
        duplicate.save()
        assert len(workbook.rows()) == 1

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
    def test_other_articles_stay_out_of_the_workbook(self, analysed, tmp_path):
        """`other` articles are stored and visible in the app, but the workbook is a
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

    def test_notify_feed_contains_only_notifying_articles(self, analysed, tmp_path):
        analysed(confidence_occurrence="کم", security_relevance="کم")
        files = workbook.export_all(tmp_path)
        assert files["important"].read_text(encoding="utf-8").strip() == ""
