# Generated by Django 4.2.5 on 2025-02-13 11:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales_management', '0014_adsreport_coupangadsreport'),
    ]

    operations = [
        migrations.AddField(
            model_name='coupangadsreport',
            name='option_name',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='option_name'),
        ),
        migrations.AddField(
            model_name='coupangadsreport',
            name='product_name',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='product_name'),
        ),
    ]
