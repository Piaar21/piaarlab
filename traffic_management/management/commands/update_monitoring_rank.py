from django.core.management.base import BaseCommand
from django.utils import timezone
from traffic_management.models import RankingMonitoring, KeywordRanking  # 실제 모델 경로에 맞게 수정하세요.
from traffic_management.api_clients import get_naver_rank  # get_naver_rank 함수의 실제 경로로 수정
from datetime import timedelta
import logging
import time
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "오늘 날짜의 순위를 (키워드 + 상품URL) 중복 없이 갱신합니다."

    def handle(self, *args, **options):
        today = timezone.localdate()

        # (1) (키워드, 상품URL) 튜플로 중복 제거
        unique_pairs = set()
        for r in RankingMonitoring.objects.all():
            for kwobj in r.keywords.all():
                # kwobj.keyword: 실제 키워드 문자열
                # r.product_url : 모니터링할 상품 URL
                unique_pairs.add((kwobj.keyword, r.product_url))

        updated = 0
        for (kw, product_url) in unique_pairs:
            # 차단 방지를 위해 텀을 두는 것도 추천
            time.sleep(0.5)

            # (2) 키워드 + URL 쌍으로 실제 API 호출
            rank = get_naver_rank(kw, product_url)
            if rank == -1:
                logger.warning("조회 실패: [%s], 상품URL=%s", kw, product_url)
                continue

            # (3) 오늘자 레코드가 있으면 업데이트, 없으면 생성
            # (모델 구조에 따라 달라집니다!)
            obj, created = KeywordRanking.objects.update_or_create(
                keyword=kw,
                product_url=product_url,  # KeywordRanking에 product_url 필드가 있어야 함
                update_at=today,
                defaults={'rank': rank},
            )
            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"중복 없이 순위 갱신 완료! 총 {updated}건 반영"
        ))