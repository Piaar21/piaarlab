# Generated by Django 4.2.5 on 2024-12-29 11:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cs_management', '0003_chatmessage_seen'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='nickname',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]