# Generated by Django 4.2.5 on 2025-02-26 12:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales_management', '0032_naveradconversiondetail_naveraddetail_naveradgroup_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='naveritem',
            name='channelProductID',
            field=models.CharField(default=123, help_text='상품ID(originProductNo)', max_length=50),
            preserve_default=False,
        ),
    ]
