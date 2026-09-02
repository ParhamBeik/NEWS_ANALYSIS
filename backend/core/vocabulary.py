"""The analyst team's vocabulary, declared exactly once.

FROZEN INVARIANT (4/4). These are not our words. `GoldTrend` holds the only four values
found in 4,304 rows across all 40 workbooks the team produced, and the only four the
workbook's own dropdown accepts. Storage, exports, the review form, prompt schemas and the
KPI tables all import from here, so nothing can offer a value the workbook would reject.

Order is meaningful for `Level`: it is an ORDINAL scale, weakest to strongest, and
`core.scoring` reads its position. Reordering these members changes every score in the
database's meaning.
"""

from __future__ import annotations

from django.db import models


class Level(models.TextChoices):
    """Ordinal confidence/impact scale. Position is the score; see core.scoring."""

    VERY_LOW = "خیلی کم", "Very low (خیلی کم)"
    LOW = "کم", "Low (کم)"
    MEDIUM = "متوسط", "Medium (متوسط)"
    HIGH = "زیاد", "High (زیاد)"
    VERY_HIGH = "خیلی زیاد", "Very high (خیلی زیاد)"


class Category(models.TextChoices):
    SECURITY = "security", "Security"
    ECONOMICS = "economics", "Economics"
    SECURITY_ECONOMICS = "security/economics", "Security/Economics"
    OTHER = "other", "Other"


class GoldTrend(models.TextChoices):
    UP = "↑", "↑ Up"
    DOWN = "↓", "↓ Down"
    NEUTRAL = "خنثی", "Neutral (خنثی)"
    UNCERTAIN = "نامطمئن", "Uncertain (نامطمئن)"


class NotifyStatus(models.TextChoices):
    NOTIFY = "اطلاع‌رسانی شود", "Notify"
    NO_NOTIFY = "اطلاع‌رسانی نشود", "Do not notify"
    # Distinct from "not notable": too few axes were assessed to decide at all.
    INSUFFICIENT = "ارزیابی ناکافی", "Insufficient assessment"


# The three axes the notify rule votes over, in the order it takes them. Storage columns,
# review-form fields, KPI rows and golden-set keys all use these exact names.
AXES: tuple[str, ...] = ("confidence_occurrence", "gold_price_impact", "security_relevance")

LEVELS: tuple[str, ...] = tuple(Level.values)
CATEGORIES: tuple[str, ...] = tuple(Category.values)
GOLD_TRENDS: tuple[str, ...] = tuple(GoldTrend.values)
