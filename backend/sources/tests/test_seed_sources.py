"""The catalog loads with its provenance labels, and aggregators can never confirm."""

import pytest
from django.core.management import CommandError, call_command

from sources.models import Source


@pytest.mark.django_db
def test_catalog_loads_labels_and_aggregators_never_confirm():
    call_command("seed_sources")

    assert Source.objects.filter(role="aggregator").count() == 2
    assert Source.objects.get(name="shahrekhabar").independence_key is None
    assert Source.objects.get(name="yjc").independence_key == "irib-state"
    ft = Source.objects.get(name="ft_world")
    assert (ft.language, ft.license_mode) == ("en", "facts_link_out")


@pytest.mark.django_db
def test_half_labelled_aggregator_is_rejected(tmp_path):
    fixture = tmp_path / "sources.yaml"
    fixture.write_text(
        "relay:\n  strategy: rss_generic\n  url: https://example.org/rss\n  role: aggregator\n"
    )
    with pytest.raises(CommandError, match="aggregator"):
        call_command("seed_sources", path=str(fixture))


@pytest.mark.django_db
def test_a_redeploy_keeps_a_source_the_operator_paused(tmp_path):
    fixture = tmp_path / "sources.yaml"
    fixture.write_text("relay:\n  strategy: rss_generic\n  url: https://example.org/rss\n")
    call_command("seed_sources", path=str(fixture))
    assert Source.objects.get(name="relay").enabled
    Source.objects.filter(name="relay").update(enabled=False)
    call_command("seed_sources", path=str(fixture))
    assert not Source.objects.get(name="relay").enabled
    Source.objects.filter(name="relay").update(enabled=True)
    fixture.write_text(fixture.read_text() + "  enabled: false\n")
    call_command("seed_sources", path=str(fixture))
    assert not Source.objects.get(name="relay").enabled
