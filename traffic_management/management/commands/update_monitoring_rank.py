from django.core.management.base import BaseCommand
from django.utils import timezone
from traffic_management.models import RankingMonitoring, KeywordRanking  # 실제 모델 경로에 맞게 수정하세요.
from traffic_management.api_clients import get_naver_rank  # get_naver_rank 함수의 실제 경로로 수정
from datetime import timedelta
import logging
import time
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "오늘 날짜의 순위를 중복 없이 갱신합니다."

    def handle(self, *args, **options):
        today = timezone.localdate()

        # 1) 중복 제거된 유니크 키워드 리스트(103개)
        keywords = list({
            kw for kw in
            RankingMonitoring.objects
                .values_list('keywords__keyword', flat=True)
        })

        updated = 0
        for kw in keywords:
            time.sleep(0.5)  # Optional: 차단 방지를 위해 딜레이
            rank = get_naver_rank(kw, /*product_url*/)
            if rank == -1:
                logger.warning("조회 실패: %s", kw)
                continue

            # 기존에 오늘자 레코드가 있으면 업데이트, 없으면 생성
            obj, created = KeywordRanking.objects.update_or_create(
                keyword=kw,
                update_at=today,
                defaults={'rank': rank},
            )
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"완료! {updated}건 반영"))
