from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("articles", "0002_alter_article_url_alter_articleimage_source_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="article",
            name="url_status",
            field=models.CharField(
                choices=[
                    ("live", "Live"),
                    ("gone", "Permanently gone (404/410)"),
                    ("dropped", "Dropped from the listing"),
                ],
                db_index=True,
                default="live",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="article",
            name="gone_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="article",
            name="gone_http_status",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="articleimage",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("stored", "Stored"),
                    ("failed", "Failed"),
                    ("gone", "Permanently gone (404/410)"),
                    ("absent", "No image published"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
    ]
