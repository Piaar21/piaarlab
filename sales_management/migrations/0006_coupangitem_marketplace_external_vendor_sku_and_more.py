# Generated by Django 4.2.5 on 2025-02-11 13:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales_management', '0005_coupangitem_marketplace_maximum_buy_count_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='coupangitem',
            name='marketplace_external_vendor_sku',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='coupangitem',
            name='rocket_external_vendor_sku',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
