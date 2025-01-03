# Generated by Django 4.2.5 on 2024-12-19 13:55

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='DelayedOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('option_code', models.CharField(max_length=100)),
                ('customer_name', models.CharField(max_length=100)),
                ('customer_contact', models.CharField(max_length=100)),
                ('order_product_name', models.CharField(blank=True, max_length=255)),
                ('order_option_name', models.CharField(blank=True, max_length=255)),
                ('seller_product_name', models.CharField(blank=True, max_length=255)),
                ('seller_option_name', models.CharField(blank=True, max_length=255)),
                ('order_number_1', models.CharField(blank=True, max_length=255)),
                ('order_number_2', models.CharField(blank=True, max_length=255)),
                ('store_name', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='ProductOptionMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('option_code', models.CharField(max_length=100, unique=True)),
                ('product_name', models.CharField(max_length=255)),
                ('option_name', models.CharField(max_length=255)),
                ('store_name', models.CharField(max_length=255)),
            ],
        ),
    ]
