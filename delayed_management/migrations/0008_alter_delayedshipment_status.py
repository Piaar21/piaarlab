# Generated by Django 4.2.5 on 2024-12-23 05:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delayed_management', '0007_delayedshipment_changed_option_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='delayedshipment',
            name='status',
            field=models.CharField(choices=[('purchase', '구매된상품들'), ('shipping', '배송중'), ('arrived', '도착완료'), ('document', '서류작성'), ('loading', '선적중'), ('nopurchase', '미구매')], default='nopurchase', max_length=20),
        ),
    ]
