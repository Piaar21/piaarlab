# Generated by Django 4.2.5 on 2025-01-30 11:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cs_management', '0012_inquiry_gpt_confidence_score_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CenterInquiry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=200)),
                ('content', models.TextField(blank=True)),
                ('author', models.CharField(blank=True, max_length=100)),
                ('answered', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
