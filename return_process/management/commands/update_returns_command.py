# myapp/management/commands/update_returns_command.py
from django.core.management.base import BaseCommand
from return_process.utils import update_returns_logic  # ← 수정된 import 경로
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Update returns data from Naver and Coupang API'

    def handle(self, *args, **options):
        logger.info("update_returns_command가 실행되었습니다.")
        update_returns_logic()
        logger.info("update_returns_command 실행 완료")
