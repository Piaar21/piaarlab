# Generated by Django 4.2.5 on 2024-12-23 03:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delayed_management', '0006_remove_delayedshipment_changed_option_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='delayedshipment',
            name='changed_option',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='customer_contact',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='customer_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='exchangeable_options',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='order_number_1',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='order_number_2',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='seller_option_name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='seller_product_name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='store_name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='delayedshipment',
            name='waiting',
            field=models.BooleanField(default=False),
        ),
    ]