# your_app/management/commands/update_naver_sales.py

from django.core.management.base import BaseCommand
from sales_management.naver_update_logic import update_naver_sales_logic

class Command(BaseCommand):
    help = "네이버 매출 데이터를 업데이트합니다."

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, help='시작 날짜 (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, help='종료 날짜 (YYYY-MM-DD)')

    def handle(self, *args, **options):
        start_str = options.get('start')
        end_str = options.get('end')
        if not start_str or not end_str:
            self.stdout.write(self.style.ERROR("날짜 인자 --start와 --end를 반드시 제공해야 합니다."))
            return
        update_naver_sales_logic(start_str, end_str)
        self.stdout.write(self.style.SUCCESS("네이버 매출 업데이트 완료"))
