from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone


def seed_paused_circuit(apps, schema_editor):
    """Inference starts paused. The weekly probe is the only path that may reopen it."""
    ProviderCircuit = apps.get_model("inference", "ProviderCircuit")
    now = timezone.now()
    ProviderCircuit.objects.get_or_create(
        pk=1,
        defaults={
            "state": "open_budget",
            "reason": "Inference paused until a weekly probe confirms provider credit.",
            "error_kind": "budget",
            "opened_at": now,
            "next_probe_at": now + timedelta(days=7),
            "last_probe_result": "open_budget",
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inference", "0002_alter_summary_article"),
    ]

    operations = [
        migrations.AlterField(
            model_name="run",
            name="status",
            field=models.CharField(
                choices=[
                    ("running", "Running"),
                    ("success", "Success"),
                    ("partial", "Partial — some nodes succeeded"),
                    ("failed", "Failed"),
                    ("aborted", "Aborted (fatal, non-budget)"),
                    ("quota_exhausted", "Stopped — provider wallet empty"),
                    ("circuit_open", "Skipped — provider circuit open"),
                    ("halted", "Halted — probes keep failing"),
                    ("no_work", "Nothing to do"),
                ],
                default="running",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="nodeevent",
            name="status",
            field=models.CharField(
                choices=[
                    ("success", "Success"),
                    ("retry", "Retrying"),
                    ("exhausted", "Retries exhausted"),
                    ("permanent", "Permanent failure"),
                    ("fatal", "Fatal"),
                    ("skipped", "Skipped (already answered)"),
                    ("aborted", "Aborted by run flag"),
                    ("circuit_open", "Skipped — provider circuit open"),
                    ("quota_exhausted", "Provider wallet empty"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="ProviderCircuit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(
                    choices=[
                        ("closed", "Closed — inference allowed"),
                        ("open_budget", "Open — provider wallet empty"),
                        ("open_errors", "Open — too many provider errors"),
                        ("probing", "Weekly wallet probe in progress"),
                        ("stopped", "Stopped — probes keep failing"),
                    ],
                    default="open_budget",
                    max_length=16,
                )),
                ("reason", models.TextField(blank=True)),
                ("error_kind", models.CharField(blank=True, max_length=32)),
                ("consecutive_failures", models.PositiveIntegerField(default=0)),
                ("probe_failures", models.PositiveIntegerField(default=0)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("next_probe_at", models.DateTimeField(blank=True, null=True)),
                ("last_probe_at", models.DateTimeField(blank=True, null=True)),
                ("last_probe_result", models.CharField(blank=True, max_length=64)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "provider circuit",
            },
        ),
        migrations.RunPython(seed_paused_circuit, migrations.RunPython.noop),
    ]
