# Generated by Django 5.1.6 on 2025-03-09 12:31

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traffic_management', '0007_alter_ranking_product_alter_task_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='RankingMonitoring',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_id', models.CharField(max_length=100, unique=True)),
                ('product_url', models.URLField()),
                ('product_name', models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name='KeywordRanking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('keyword', models.CharField(max_length=255)),
                ('rank', models.PositiveIntegerField()),
                ('ranking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='keywords', to='traffic_management.rankingmonitoring')),
            ],
        ),
    ]
