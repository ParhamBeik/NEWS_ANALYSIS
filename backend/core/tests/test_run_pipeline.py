"""The stage map must name tasks that exist.

Writing this command by hand, three of the ten entries pointed at the wrong module or a
task name that had been renamed - and every one of them would have failed at the moment an
operator reached for it, which is by definition a moment something is already wrong. A
mapping of strings to strings gets no help from the type checker, so it needs a test.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands.run_pipeline import STAGES


@pytest.mark.parametrize("stage", sorted(STAGES))
def test_every_stage_resolves_to_a_real_celery_task(stage):
    module_path, task_name = STAGES[stage]
    module = __import__(module_path, fromlist=[task_name])
    task = getattr(module, task_name, None)
    assert task is not None, f"{module_path}.{task_name} does not exist"
    assert hasattr(task, "delay"), f"{module_path}.{task_name} is not a Celery task"


def test_limit_is_rejected_for_a_stage_that_cannot_take_it(db):
    """Fails here, in the operator's terminal, rather than inside a worker minutes later
    in a log nobody is watching."""
    with pytest.raises(CommandError, match="does not take --limit"):
        call_command("run_pipeline", "canary", "--limit", "5")


def test_an_unknown_stage_is_rejected_by_argparse(db):
    with pytest.raises((CommandError, SystemExit)):
        call_command("run_pipeline", "not-a-stage")


class TestRebuildAll:
    def test_rebuild_all_reaches_the_workbook_task(self, monkeypatch):
        """The scheduled export is bounded to the rolling window, so the operator needs a
        documented way past it after an import - not a `manage.py shell` incantation."""
        seen = {}
        monkeypatch.setattr(
            "exports.tasks.build_daily_workbook.delay",
            lambda **kwargs: seen.update(kwargs) or type("R", (), {"id": "x"})(),
        )
        call_command("run_pipeline", "workbook", "--rebuild-all")
        assert seen == {"rebuild_all": True}

    def test_a_stage_that_does_not_take_it_says_so(self):
        """Failing here beats an unexpected kwarg failing inside a worker minutes later, in
        a log nobody is watching."""
        with pytest.raises(CommandError, match="does not take --rebuild-all"):
            call_command("run_pipeline", "crawl", "--rebuild-all")
