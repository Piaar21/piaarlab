# Generated by Django 4.2.5 on 2025-02-11 12:23

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('sales_management', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='coupangitemimage',
            name='parent_item',
        ),
        migrations.DeleteModel(
            name='CoupangItem',
        ),
        migrations.DeleteModel(
            name='CoupangItemImage',
        ),
        migrations.DeleteModel(
            name='CoupangItemList',
        ),
    ]
