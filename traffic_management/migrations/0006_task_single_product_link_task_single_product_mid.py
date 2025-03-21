# Generated by Django 5.1.6 on 2025-03-07 13:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traffic_management', '0005_alter_traffic_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='single_product_link',
            field=models.URLField(blank=True, null=True, verbose_name='단일상품링크'),
        ),
        migrations.AddField(
            model_name='task',
            name='single_product_mid',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='단일상품 MID값'),
        ),
    ]
