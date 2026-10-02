"""Map stored reader-event categories onto the eight investor topics.

Only the read projection (NewsEvent.category) is rewritten. Assessments and reviews are
append-only history and keep their slugs; readers normalise them with
core.vocabulary.event_topic. The mapping is copied here, not imported, so this migration
means the same thing after the vocabulary changes again.
"""

from django.db import migrations

LEGACY = {
    "monetary": "macro_monetary",
    "macro": "macro_monetary",
    "sanctions_trade": "sanctions_diplomacy",
    "geopolitics": "sanctions_diplomacy",
    "energy": "energy_commodities",
    "markets": "markets_companies",
}


def forwards(apps, schema_editor):
    NewsEvent = apps.get_model("articles", "NewsEvent")
    for old, new in LEGACY.items():
        NewsEvent.objects.filter(category=old).update(category=new)


class Migration(migrations.Migration):
    dependencies = [("articles", "0013_widen_seen_run")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
