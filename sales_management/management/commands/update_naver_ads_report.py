# your_app/management/commands/update_naver_ads_report.py

from django.core.management.base import BaseCommand
from sales_management.naver_update_logic import update_naver_ads_report_logic

class Command(BaseCommand):
    help = "네이버 광고 리포트 데이터를 업데이트합니다."

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, help='시작 날짜 (YYYY-MM-DD)', default='')
        parser.add_argument('--end', type=str, help='종료 날짜 (YYYY-MM-DD)', default='')

    def handle(self, *args, **options):
        raw_start = options.get('start')
        raw_end = options.get('end')
        update_naver_ads_report_logic(raw_start, raw_end)
        self.stdout.write(self.style.SUCCESS("네이버 광고 리포트 업데이트 완료"))
