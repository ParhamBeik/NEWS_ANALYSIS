"""The alert rule as pure functions: dial, breaking, re-alert, quiet hours and the cap."""

from datetime import time

from core import alerts


def test_dial_sets_the_lowest_alerting_tier():
    assert alerts.reason(watched=True, tier=2, global_tier=1, dial="low") == "watch"
    assert alerts.reason(watched=True, tier=2, global_tier=1, dial="medium") == ""
    assert alerts.reason(watched=True, tier=3, global_tier=1, dial="medium") == "watch"
    assert alerts.reason(watched=True, tier=3, global_tier=1, dial="high") == ""
    assert alerts.reason(watched=True, tier=4, global_tier=1, dial="high") == "watch"


def test_unwatched_events_alert_only_when_global_tier_five():
    assert alerts.reason(watched=False, tier=5, global_tier=4, dial="low") == ""
    assert alerts.reason(watched=False, tier=1, global_tier=5, dial="high") == "breaking"
    assert alerts.reason(watched=True, tier=None, global_tier=None, dial="low") == ""


def test_update_only_on_evidence_flip_or_tier_rise():
    assert alerts.change(None, 3, "single") == "new"
    assert alerts.change((3, "single"), 3, "single") == ""
    assert alerts.change((3, "single"), 2, "single") == ""
    assert alerts.change((3, "single"), 4, "single") == "update"
    assert alerts.change((3, "single"), 3, "multi") == "update"


def test_quiet_hours_wrap_midnight():
    start, end = time(23, 0), time(7, 0)
    assert alerts.in_quiet_hours(time(23, 30), start, end)
    assert alerts.in_quiet_hours(time(3, 0), start, end)
    assert not alerts.in_quiet_hours(time(7, 0), start, end)
    assert not alerts.in_quiet_hours(time(12, 0), start, end)
    assert alerts.in_quiet_hours(time(13, 0), time(12, 0), time(14, 0))
    assert not alerts.in_quiet_hours(time(13, 0), time(9, 0), time(9, 0))


def test_cap_and_quiet_hold_pushes_but_tier_five_breaks_through():
    assert alerts.hold(exempt=False, quiet=False, pushed_today=4) == ""
    assert alerts.hold(exempt=False, quiet=False, pushed_today=5) == "cap"
    assert alerts.hold(exempt=False, quiet=True, pushed_today=0) == "quiet"
    assert alerts.hold(exempt=True, quiet=True, pushed_today=99) == ""
