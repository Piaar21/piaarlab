# Generated by Django 4.2.5 on 2024-12-29 09:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cs_management', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatmessage',
            name='image_url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
