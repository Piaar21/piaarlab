# Generated by Django 5.1.4 on 2024-12-14 08:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('return_process', '0005_alter_returnitem_claim_type_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='returnitem',
            name='return_shipping_charge',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
    ]
