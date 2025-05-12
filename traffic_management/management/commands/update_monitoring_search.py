from django.core.management.base import BaseCommand
from traffic_management.models import KeywordRanking  # 실제 모델 경로에 맞게 수정하세요.
from traffic_management.api_clients import get_rel_keywords  # get_rel_keywords 함수의 실제 경로로 수정
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "등록된 KeywordRanking의 각 키워드에 대해 한 달 검색량을 업데이트합니다."

    def handle(self, *args, **options):
        # 1) 중복 제거된 키워드 리스트만 뽑기
        unique_keywords = KeywordRanking.objects \
            .values_list('keyword', flat=True) \
            .distinct()

        updated_count = 0

        for kw in unique_keywords:
            # API 호출은 키워드당 한 번만!
            df = get_rel_keywords([kw])
            if df is None or df.empty:
                logger.warning("키워드 [%s] 검색량 조회 실패 또는 결과 없음", kw)
                continue

            total_search = int(df.iloc[0].get('totalSearchCount', 0))

            # 같은 키워드를 가진 레코드 중, 실제 값이 바뀌는 것만 한꺼번에 업데이트
            changed = KeywordRanking.objects \
                .filter(keyword=kw) \
                .exclude(search_volume=total_search) \
                .update(search_volume=total_search)

            if changed:
                logger.info("키워드 [%s] 검색량 업데이트: %d건 → %d", kw, changed, total_search)
                updated_count += changed
            else:
                logger.debug("키워드 [%s] 검색량 미변경 (값: %d)", kw, total_search)

        self.stdout.write(self.style.SUCCESS(f"검색량 업데이트 완료! ({updated_count}건 반영)"))
