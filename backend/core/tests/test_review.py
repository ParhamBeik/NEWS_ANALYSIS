from datetime import timedelta

import pytest
from django.utils import timezone

from articles.models import EventAssessment, EventReview, EventRevision, NewsEvent
from core.events import attach_article, split_article_from_event
from core.review import record_decision, review_queue, review_stats, score_tier

pytestmark = pytest.mark.django_db


def make_review(make_article, *, reason="audit_sample", confidence=0.8, category="macro",
                iran=75, global_=25):
    event = attach_article(make_article())
    NewsEvent.objects.filter(pk=event.pk).update(
        category=category, iran_score=iran, global_score=global_,
        assessment_confidence=confidence,
    )
    EventAssessment.objects.create(
        event=event, model="jev", evidence_hash="x", category=category, iran_score=iran,
        global_score=global_, confidence=confidence,
    )
    event.refresh_from_db()
    return EventReview.objects.create(event=event, reason=reason)


def test_score_tier_maps_jev_steps_and_neighbours():
    assert [score_tier(s) for s in (0, 12, 13, 25, 50, 62, 63, 75, 88, 100)] == [
        0, 0, 1, 1, 2, 2, 3, 3, 4, 4,
    ]
    assert score_tier(None) is None


def test_queue_puts_uncertain_then_low_confidence_then_merged_then_audit(make_article):
    audit_low = make_review(make_article, confidence=0.3)
    audit_merged = make_review(make_article, confidence=0.9)
    audit_plain = make_review(make_article, confidence=0.9)
    uncertain_high = make_review(make_article, reason="high_impact_uncertain", confidence=0.6)
    uncertain_low = make_review(make_article, reason="high_impact_uncertain", confidence=0.4)
    skipped = make_review(make_article, reason="high_impact_uncertain", confidence=0.1)
    skipped.skipped_at = timezone.now()
    skipped.save()
    EventRevision.objects.create(event=audit_merged.event, reason="merged_event")
    done = make_review(make_article, reason="high_impact_uncertain", confidence=0.1)
    record_decision(done, None, "agree")

    assert [row.pk for row in review_queue()] == [
        uncertain_low.pk, uncertain_high.pk, audit_low.pk, audit_merged.pk, audit_plain.pk,
        skipped.pk,
    ]


def test_agree_fix_and_undo_write_the_review(make_article, user):
    review = make_review(make_article, iran=62, global_=25)
    record_decision(review, user, "agree")
    review.refresh_from_db()
    assert (review.status, review.reviewed_category, review.reviewed_iran_score,
            review.reviewed_global_score, review.reviewer) == ("reviewed", "macro", 62, 25, user)
    assert review.reviewed_at is not None

    record_decision(review, user, "fix", category="energy", iran_tier=4, global_tier=0)
    review.refresh_from_db()
    assert (review.reviewed_category, review.reviewed_iran_score,
            review.reviewed_global_score) == ("energy", 100, 0)

    record_decision(review, user, "undo")
    review.refresh_from_db()
    assert (review.status, review.reviewed_iran_score, review.reviewer) == ("pending", None, None)

    with pytest.raises(ValueError):
        record_decision(review, user, "fix", category="sports", iran_tier=1, global_tier=1)
    with pytest.raises(ValueError):
        record_decision(review, user, "fix", category="energy", iran_tier=5, global_tier=1)


def test_stats_compare_against_the_judgment_shown_at_review_time(make_article, user):
    agreed = make_review(make_article, category="macro", iran=75, global_=25)
    record_decision(agreed, user, "agree")
    fixed = make_review(make_article, category="energy", iran=75, global_=25)
    record_decision(fixed, user, "fix", category="energy", iran_tier=1, global_tier=1)
    # A later reassessment must not rewrite the recorded agreement.
    EventAssessment.objects.create(
        event=agreed.event, model="jev", evidence_hash="y", category="energy", iran_score=0,
        global_score=0, confidence=0.9,
    )

    stats = review_stats()
    assert (stats["reviewed"], stats["agreed"], stats["agreement_rate"]) == (2, 1, 0.5)
    by_category = {row["category"]: row for row in stats["categories"]}
    assert by_category["macro"]["agreement_rate"] == 1.0
    assert by_category["energy"]["category_match_rate"] == 1.0
    assert by_category["energy"]["tier_match_rate"] == 0.0
    later = review_stats(since=timezone.now() + timedelta(minutes=1), reviewer=user)
    assert later["reviewed"] == 0 and later["agreement_rate"] is None


def test_split_moves_the_article_and_its_copies_to_a_new_event(make_article):
    first = make_article()
    event = attach_article(first)
    stray = make_article()
    copy = make_article(duplicate_of=stray)
    event.articles.add(stray, copy)

    split = split_article_from_event(event.pk, stray.pk)

    assert split.primary_article_id == stray.pk
    assert set(split.articles.values_list("id", flat=True)) == {stray.pk, copy.pk}
    assert list(event.articles.values_list("id", flat=True)) == [first.pk]


def test_split_of_the_primary_promotes_the_remaining_report(make_article):
    first = make_article(published_at=timezone.now() - timedelta(hours=2))
    event = attach_article(first)
    other = make_article()
    event.articles.add(other)

    split = split_article_from_event(event.pk, first.pk)

    event.refresh_from_db()
    assert event.primary_article_id == other.pk
    assert split.primary_article_id == first.pk
    with pytest.raises(ValueError):
        split_article_from_event(event.pk, other.pk)
    with pytest.raises(ValueError):
        split_article_from_event(event.pk, first.pk)
