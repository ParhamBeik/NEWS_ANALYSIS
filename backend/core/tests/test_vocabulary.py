"""FROZEN INVARIANT 4/4 - the workbook vocabulary is the team's, not ours.

These exact strings are what the team's Excel dropdown accepts. A "tidy-up" that
normalises a space, swaps a Persian YEH for an Arabic one, or reorders the ordinal scale
produces a workbook the team's own file rejects - silently, cell by cell.
"""

from __future__ import annotations

from core.vocabulary import AXES, CATEGORIES, GOLD_TRENDS, LEVELS, Level, NotifyStatus


def test_levels_are_the_five_workbook_values_in_ordinal_order():
    assert LEVELS == ("خیلی کم", "کم", "متوسط", "زیاد", "خیلی زیاد")


def test_gold_trends_are_the_only_four_values_in_4304_workbook_rows():
    assert GOLD_TRENDS == ("↑", "↓", "خنثی", "نامطمئن")


def test_categories_match_the_classification_schema():
    assert CATEGORIES == ("security", "economics", "security/economics", "other")


def test_axes_are_the_three_the_notify_rule_votes_over():
    assert AXES == ("confidence_occurrence", "gold_price_impact", "security_relevance")


def test_notify_statuses_are_the_workbook_strings():
    assert NotifyStatus.NOTIFY.value == "اطلاع‌رسانی شود"
    assert NotifyStatus.NO_NOTIFY.value == "اطلاع‌رسانی نشود"
    assert NotifyStatus.INSUFFICIENT.value == "ارزیابی ناکافی"


def test_level_member_order_is_the_ordinal_scale():
    """`Level.values` order IS the score. Reordering members silently rescores the
    entire database, so the mapping is pinned here rather than implied."""
    assert list(Level.values) == list(LEVELS)


def test_jev_topics_are_the_event_vocabulary_and_legacy_slugs_map_into_it():
    from core.vocabulary import EVENT_CATEGORIES, LEGACY_EVENT_CATEGORIES, event_topic
    from inference.jev import CATEGORIES as JEV_TOPICS

    assert tuple(JEV_TOPICS) == EVENT_CATEGORIES
    assert set(LEGACY_EVENT_CATEGORIES.values()) <= set(EVENT_CATEGORIES)
    assert event_topic("geopolitics") == "sanctions_diplomacy"
    assert event_topic("disasters") == "disasters"
