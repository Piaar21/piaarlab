# Generated by Django 4.2.5 on 2025-01-11 07:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delayed_management', '0019_delayedshipment_changed_option_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='delayedshipment',
            name='message_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]