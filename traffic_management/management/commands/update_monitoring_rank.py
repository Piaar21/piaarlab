from django.core.management.base import BaseCommand
from django.utils import timezone
from traffic_management.models import RankingMonitoring, KeywordRanking  # 실제 모델 경로에 맞게 수정하세요.
from traffic_management.api_clients import get_naver_rank  # get_naver_rank 함수의 실제 경로로 수정
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "오늘 날짜의 순위를 갱신합니다. (이전 날짜의 레코드는 수정하지 않습니다.)"

    def handle(self, *args, **options):
        today = timezone.now().date()
        updated_count = 0
        # 모든 RankingMonitoring 인스턴스와 연결된 키워드들을 가져옴
        rankings = RankingMonitoring.objects.all().prefetch_related('keywords')
        for r in rankings:
            for kwobj in r.keywords.all():
                product_url = r.product_url
                new_rank = get_naver_rank(kwobj.keyword, product_url)
                if new_rank == -1:
                    logger.warning("키워드 [%s]의 순위 조회 실패 (제품 URL: %s)", kwobj.keyword, product_url)
                    continue

                existing_today = KeywordRanking.objects.filter(
                    ranking=r, 
                    keyword=kwobj.keyword,
                    update_at=today
                ).first()

                if existing_today:
                    existing_today.rank = new_rank
                    existing_today.save()
                    logger.info("기존 레코드 업데이트: [%s] 순위 %d", kwobj.keyword, new_rank)
                else:
                    KeywordRanking.objects.create(
                        ranking=r,
                        keyword=kwobj.keyword,
                        rank=new_rank,
                        update_at=today
                    )
                    logger.info("새 레코드 생성: [%s] 순위 %d", kwobj.keyword, new_rank)
                updated_count += 1
        self.stdout.write(self.style.SUCCESS(f"순위 업데이트 완료! ({updated_count}건 반영)"))
