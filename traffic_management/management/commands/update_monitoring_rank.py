from django.core.management.base import BaseCommand
from django.utils import timezone
from traffic_management.models import RankingMonitoring, KeywordRanking
from traffic_management.api_clients import get_naver_rank
from datetime import timedelta
import logging, time

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "오늘 날짜의 순위를 (키워드 + 모니터링 객체) 중복 없이 갱신합니다."

    def handle(self, *args, **options):
        today = timezone.localdate()

        # (1) (RankingMonitoring 인스턴스, 키워드) 튜플로 중복 제거
        unique_pairs = set()
        for monitor in RankingMonitoring.objects.all():
            for kwobj in monitor.keywords.all():
                unique_pairs.add((monitor, kwobj.keyword))

        updated = 0
        for monitor, kw in unique_pairs:
            time.sleep(0.5)  # API 차단 방지

            # (2) 실제 API 호출 (모니터링 객체에서 URL 꺼내 쓰기)
            rank = get_naver_rank(kw, monitor.product_url)

            if rank == -1:
                logger.warning("조회 실패: [%s], URL=%s ⇒ -1 처리", kw, monitor.product_url)
                obj, created = KeywordRanking.objects.update_or_create(
                    ranking=monitor,
                    keyword=kw,
                    update_at=today,
                    defaults={'rank': -1},
                )
            else:
                obj, created = KeywordRanking.objects.update_or_create(
                    ranking=monitor,
                    keyword=kw,
                    update_at=today,
                    defaults={'rank': rank},
                )

            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"중복 없이 순위 갱신 완료! 총 {updated}건 반영"
        ))
