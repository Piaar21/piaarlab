# Generated by Django 5.1.6 on 2025-05-09 06:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traffic_management', '0025_task_store_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='keywordranking',
            name='rank',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
