"""The vocabulary contract between the two halves of the repository.

`core.vocabulary` is declared once and imported everywhere on the Python side, so nothing
in the backend can offer a value the workbook would reject. The frontend cannot import it.
It re-declares the same four vocabularies in `lib/display.js` and `app/page.js` — for
ordering, colour and button labels — and there is no compiler, no type and no runtime check
standing between the two copies.

Each drift fails differently, and two of the three fail SILENTLY:

- `notify` is a ChoiceFilter, so a wrong value is a 400 and the feed renders its error
  boundary. Loud. This one already happened: the frontend shipped «اطلاعات ناکافی» against
  the vocabulary's «ارزیابی ناکافی» — three characters apart, invisible in review, and the
  "Insufficient" option was broken from the day it was written.
- A wrong LEVEL or trend value posts a label the submit serializer rejects by name. Loud,
  but only once a human has already typed the review.
- A wrong AXIS KEY is silent. `ReviewSubmitSerializer` declares each axis as an optional
  field, so DRF simply drops an unrecognised key: the reviewer's answer is accepted, stored
  as NULL, and every /kpi denominator quietly loses it. The scarcest data in the system,
  discarded with no error anywhere.

These tests parse the JavaScript rather than importing it, which is ugly and is still the
cheapest thing that can fail when the two disagree. Every one asserts it actually found
something first, so a rename that breaks the parsing fails loudly instead of passing empty.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from core.vocabulary import AXES, Category, GoldTrend, Level, NotifyStatus

FRONTEND = Path(settings.BASE_DIR).parent / "frontend"


def _source(*parts: str) -> str:
    path = FRONTEND.joinpath(*parts)
    if not path.exists():
        pytest.skip("frontend tree not present (backend-only image)")
    return path.read_text(encoding="utf-8")


def _array_literal(source: str, name: str) -> list[str]:
    """The string members of `export const NAME = [...]`, in order."""
    match = re.search(rf"export const {name} = \[(.*?)\];", source, re.S)
    assert match, f"{name} moved or changed shape; this test needs to follow it"
    return re.findall(r'"([^"]+)"', match.group(1))


def _object_keys(source: str, name: str) -> list[str]:
    """The keys of `export const NAME = {...}`, in order.

    Both spellings, because the file uses both: a bare identifier where the key is a plain
    slug (`security:`) and a quoted string everywhere else - which is most of them here,
    since a Persian level like «خیلی کم» contains a space.
    """
    match = re.search(rf"export const {name} = \{{(.*?)\n\}};", source, re.S)
    assert match, f"{name} moved or changed shape; this test needs to follow it"
    pairs = re.findall(r'^\s*(?:"([^"]+)"|([A-Za-z_$][\w$]*))\s*:', match.group(1), re.M)
    return [quoted or bare for quoted, bare in pairs]


def test_the_feeds_verdict_filter_offers_only_values_the_filter_accepts():
    """`notify` is a ChoiceFilter: a value the backend does not have is a 400, not a filter
    that quietly matches nothing."""
    offered = re.findall(
        r'\["([^"]+)",\s*"(?:Notify|Quiet|Insufficient)"\]',
        _source("app", "page.js"),
    )
    assert offered, "the feed's NOTIFY_STATES list moved; this test needs to follow it"
    assert offered == list(NotifyStatus.values)


def test_the_review_forms_level_buttons_match_the_ordinal_scale():
    """Order, not just membership. `levelIndex` renders "3/5" from this array's position,
    and `core.scoring` reads the score from the SAME position on the other side - so a
    reordering here shows the analyst a severity the pipeline never computed."""
    assert _array_literal(_source("lib", "display.js"), "LEVEL_ORDER") == list(Level.values)


def test_the_axis_keys_match_the_ones_the_serializer_accepts():
    """The silent one. An unrecognised key is dropped by DRF, so the reviewer's answer is
    accepted and stored as NULL."""
    assert _object_keys(_source("lib", "display.js"), "AXIS_LABEL") == list(AXES)


@pytest.mark.parametrize(
    "constant, expected",
    [
        ("CATEGORY_LABEL", Category.values),
        ("CATEGORY_STYLE", Category.values),
        ("LEVEL_STYLE", Level.values),
        ("TREND_STYLE", GoldTrend.values),
    ],
)
def test_every_display_map_covers_exactly_the_stored_vocabulary(constant, expected):
    """A missing key renders an unstyled badge; an extra one is a value nothing can store,
    which means it was copied from somewhere that is no longer the source of truth."""
    assert _object_keys(_source("lib", "display.js"), constant) == list(expected)
