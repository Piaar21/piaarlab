# Generated by Django 4.2.5 on 2024-12-19 14:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delayed_management', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='OptionStoreMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('option_code', models.CharField(max_length=100, unique=True)),
                ('store_name', models.CharField(max_length=255)),
            ],
        ),
    ]