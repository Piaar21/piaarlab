# Generated by Django 5.1.3 on 2024-12-13 06:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('return_process', '0003_alter_returnitem_claim_reason_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='returnitem',
            name='claim_request_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]