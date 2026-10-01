import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def test_reader_gate_fails_closed_without_reviewed_evidence():
    with pytest.raises(CommandError, match="reviewed sample is too small"):
        call_command("reader_release_gate", min_reviewed=100, min_priority_items=100)
