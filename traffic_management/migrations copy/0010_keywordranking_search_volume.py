# Generated by Django 5.1.6 on 2025-03-09 13:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traffic_management', '0009_keywordranking_update_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='keywordranking',
            name='search_volume',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
