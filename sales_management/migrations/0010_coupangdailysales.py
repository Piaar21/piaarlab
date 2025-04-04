# Generated by Django 4.2.5 on 2025-02-12 12:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales_management', '0009_coupangproduct_categoryid_coupangproduct_productid'),
    ]

    operations = [
        migrations.CreateModel(
            name='CoupangDailySales',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('displayed_product_id', models.CharField(max_length=255, verbose_name='Displayed Product ID')),
                ('sku_id', models.CharField(max_length=255, verbose_name='SKU ID')),
                ('item_name', models.CharField(max_length=255, verbose_name='itemName')),
                ('delivery_label', models.CharField(max_length=255, verbose_name='delivery_label')),
                ('category_name', models.CharField(max_length=255, verbose_name='category name')),
                ('item_winner_ratio', models.DecimalField(decimal_places=2, max_digits=5, verbose_name='Item Winner Ratio')),
                ('net_sales_amount', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='Net Sales Amount')),
                ('net_sold_items', models.IntegerField(verbose_name='Net Sold Items')),
                ('total_transaction_amount', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='Total Transaction Amount')),
                ('total_transaction_items', models.IntegerField(verbose_name='Total Transaction Items')),
                ('total_cancellation_amount', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='Total Cancellation Amount')),
                ('total_cancelled_items', models.IntegerField(verbose_name='Total Cancelled Items')),
                ('immediate_cancellation_items', models.IntegerField(verbose_name='Immediate Cancellation Items')),
                ('date', models.DateField(auto_now_add=True, verbose_name='Date')),
            ],
        ),
    ]
