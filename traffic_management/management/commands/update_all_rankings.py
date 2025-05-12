from django.core.management.base import BaseCommand
from django.utils import timezone
from traffic_management.models import Task, Ranking
from traffic_management.views import get_naver_rank   # 해당 함수들이 있다면 임포트
from traffic_management.tasks import update_task_status
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "모든 작업의 순위를 업데이트합니다."

    def handle(self, *args, **options):
        tasks = Task.objects.filter(is_completed=False)
        today = timezone.now().date()
        for task in tasks:
            try:
                current_rank = get_naver_rank(task.keyword.name, task.url)
                if current_rank == -1 or current_rank > 1000:
                    current_rank = None
            except Exception as e:
                logger.error(f"작업 ID {task.id}의 순위 업데이트 중 오류 발생: {e}")
                current_rank = task.current_rank

            difference_rank = (
                (task.current_rank - current_rank)
                if task.current_rank is not None and current_rank is not None
                else None
            )
            task.yesterday_rank = task.current_rank
            task.current_rank = current_rank
            task.difference_rank = difference_rank
            task.last_checked_date = timezone.now()

            if today > task.available_end_date:
                if not task.is_completed:
                    task.is_completed = True
                    task.ending_rank = task.current_rank
            task.save()

            if task.product:
                Ranking.objects.create(
                    product=task.product,
                    keyword=task.keyword,
                    rank=current_rank,
                    date_time=timezone.now(),
                    task=task,
                )
            else:
                logger.error(f"Task ID {task.id} has no associated product; skipping Ranking creation.")
            
            update_task_status(task)
        
        self.stdout.write(self.style.SUCCESS("모든 작업의 순위가 업데이트되었습니다."))
