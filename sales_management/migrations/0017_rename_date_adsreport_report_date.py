# Generated by Django 4.2.5 on 2025-02-13 13:27

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sales_management', '0016_coupangadsreport_unique_report_by_date_option_imp_click_spend_orders'),
    ]

    operations = [
        migrations.RenameField(
            model_name='adsreport',
            old_name='date',
            new_name='report_date',
        ),
    ]
