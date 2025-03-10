from django.core.management.base import BaseCommand
from traffic_management.models import KeywordRanking  # 실제 모델 경로에 맞게 수정하세요.
from traffic_management.api_clients import get_rel_keywords  # get_rel_keywords 함수의 실제 경로로 수정
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "등록된 KeywordRanking의 각 키워드에 대해 한 달 검색량을 업데이트합니다."

    def handle(self, *args, **options):
        keyword_qs = KeywordRanking.objects.all()
        updated_count = 0
        for kwobj in keyword_qs:
            # API를 통해 키워드 검색량 조회
            df = get_rel_keywords([kwobj.keyword])
            if df is not None and not df.empty:
                row = df.iloc[0]
                total_search = int(row.get('totalSearchCount', 0))
                kwobj.search_volume = total_search
                kwobj.save()
                updated_count += 1
                logger.info("키워드 [%s] 검색량 업데이트: %d", kwobj.keyword, total_search)
        self.stdout.write(self.style.SUCCESS(f"검색량 업데이트 완료! ({updated_count}건 반영)"))
