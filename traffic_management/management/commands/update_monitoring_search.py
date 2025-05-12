import time
import logging

from django.core.management.base import BaseCommand
from traffic_management.models import KeywordRanking
from traffic_management.api_clients import get_rel_keywords

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "등록된 KeywordRanking의 각 키워드에 대해 한 달 검색량을 업데이트합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            '--delay', '-d',
            type=float,
            default=1.0,
            help='각 API 호출 사이에 대기할 시간(초), 기본 1.0초'
        )

    def handle(self, *args, **options):
        delay = options['delay']

        # 1) 중복 제거된 키워드 리스트만 뽑기
        unique_keywords = KeywordRanking.objects \
            .values_list('keyword', flat=True) \
            .distinct()

        updated_count = 0

        for kw in unique_keywords:
            try:
                # API 호출 (필요 시 get_rel_keywords 에 timeout 파라미터를 추가하세요)
                df = get_rel_keywords([kw])
            except Exception as e:
                logger.warning("키워드 [%s] 호출 에러: %s", kw, e)
                # 에러 시 약간 더 길게 대기
                time.sleep(delay * 2)
                continue

            if df is None or df.empty:
                logger.warning("키워드 [%s] 검색량 조회 실패 또는 결과 없음", kw)
            else:
                total_search = int(df.iloc[0].get('totalSearchCount', 0))

                # 같은 키워드를 가진 레코드 중, 값이 바뀌는 것만 업데이트
                changed = KeywordRanking.objects \
                    .filter(keyword=kw) \
                    .exclude(search_volume=total_search) \
                    .update(search_volume=total_search)

                if changed:
                    logger.info("키워드 [%s] 검색량 업데이트: %d건 → %d", kw, changed, total_search)
                    updated_count += changed
                else:
                    logger.debug("키워드 [%s] 검색량 미변경 (값: %d)", kw, total_search)

            # 다음 호출 전 딜레이
            time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(f"검색량 업데이트 완료! ({updated_count}건 반영)"))
