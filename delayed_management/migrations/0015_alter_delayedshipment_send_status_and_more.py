# Generated by Django 4.2.5 on 2024-12-23 14:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delayed_management', '0014_alter_delayedshipment_send_status_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='delayedshipment',
            name='send_status',
            field=models.CharField(choices=[('none', '발송 전'), ('pending', '대기'), ('success', '성공'), ('failed', '실패')], default='NONE', help_text='전송 상태(대기, 전송중, 성공, 실패)', max_length=10),
        ),
        migrations.AlterField(
            model_name='delayedshipment',
            name='send_type',
            field=models.CharField(choices=[('none', '미발송'), ('sms', '문자'), ('kakao', '알림톡')], default='NONE', help_text='문자(SMS), 알림톡(KAKAO), 혹은 미전송(NONE) 등', max_length=10),
        ),
    ]