from django.utils import timezone
import datetime
from .views import get_daily_search_volume_from_rel_keywords, compute_recent_7day_sales_and_growth
def get_monthly_volume(task):
    """
    주어진 Task의 keyword를 기반으로, 최근 30일 동안의 일별 검색량을 추출하고,
    이를 모두 합산하여 반환합니다.
    
    반환값 예:
      0 이상 (int): 최근 30일 합산 검색량
    """
    # 키워드가 없는 경우 0
    if not task.keyword:
        return 0

    # 기간: 오늘부터 29일 전까지 (총 30일)
    today_date = timezone.now().date()
    start_date = (today_date - datetime.timedelta(days=29)).strftime("%Y-%m-%d")
    end_date = today_date.strftime("%Y-%m-%d")

    # 이미 작성된 함수 사용
    # get_daily_search_volume_from_rel_keywords(keywords, start_date, end_date)
    # -> { '키워드': [ { period: 'YYYY-MM-DD', searchVolume: int }, ... ] }
    daily_data_dict = get_daily_search_volume_from_rel_keywords([task.keyword.name], start_date, end_date)
    if not daily_data_dict or task.keyword.name not in daily_data_dict:
        return 0

    daily_data = daily_data_dict[task.keyword.name]
    total_volume = sum(item.get("searchVolume", 0) for item in daily_data)
    return total_volume

def is_recent_sales_decreasing(task):
    """
    주어진 Task의 single_product_mid를 사용해, 최근 7일 매출액이
    '기준 창(available_start_date 기준 7일)' 대비 감소했는지 여부를 True/False로 반환합니다.
    
    compute_recent_7day_sales_and_growth()에서 반환되는 sales_growth가 음수이면 True, 
    그렇지 않으면 False 처리.
    """
    # product_mid나 시작일이 없으면 판단 불가 -> 감소로 치지 않고 False
    if not task.single_product_mid or not task.available_start_date:
        return False

    recent_sales, sales_growth_str = compute_recent_7day_sales_and_growth(
        task.single_product_mid, 
        task.available_start_date
    )
    # sales_growth_str 예: "+10.0%", "0%", "-3.2%"
    if sales_growth_str.startswith('-'):
        # 음수이면 매출 감소
        return True
    return False



import datetime
from django.utils import timezone
from .models import Ranking
# 아래 두 헬퍼 함수를 같은 파일에 두거나, 별도의 utils.py에 두고 import할 수 있습니다:
# from .utils import get_monthly_volume, is_recent_sales_decreasing

def update_task_status(task):
    # 1) 날짜 계산
    days_since_start = (timezone.now().date() - task.available_start_date).days
    if days_since_start < 3:
        task.status = '로딩중'
        task.save()
        return

    # 2) 현재 순위, 시작 순위
    current_rank = task.current_rank
    initial_rank = task.start_rank
    if current_rank is None:
        task.status = '효과없음'
        task.save()
        return

    # 3) 3일 전, 6일 전 순위 조회
    three_days_ago = timezone.now() - datetime.timedelta(days=3)
    six_days_ago = timezone.now() - datetime.timedelta(days=6)

    three_days_ago_ranking = (Ranking.objects.filter(
        task=task,
        date_time__lte=three_days_ago
    ).order_by('-date_time').first())
    six_days_ago_ranking = (Ranking.objects.filter(
        task=task,
        date_time__lte=six_days_ago
    ).order_by('-date_time').first())

    three_days_ago_rank = three_days_ago_ranking.rank if three_days_ago_ranking else None
    six_days_ago_rank = six_days_ago_ranking.rank if six_days_ago_ranking else None

    # 구간별 구분
    def get_zone_name(rank_val):
        if rank_val is None:
            return 'NONE'
        elif rank_val <= 6:
            return 'TOP6'
        elif rank_val <= 40:
            return 'TOP40'
        else:
            return 'OUTSIDE40'

    start_zone = get_zone_name(initial_rank)
    current_zone = get_zone_name(current_rank)

    # 기본 로직
    if start_zone == 'TOP6':
        if current_rank > 6:
            task.status = '효과없음'
        else:
            task.status = '굿굿'
    elif start_zone == 'TOP40':
        if current_rank <= 6:
            task.status = '굿굿'
        elif current_rank <= 40:
            task.status = '살짝오름'
        else:
            task.status = '효과없음'
    else:
        if current_rank <= 6:
            task.status = '굿굿'
        elif current_rank <= 40:
            task.status = '살짝오름'
        else:
            task.status = '효과없음'

    # 3일 전 대비
    if three_days_ago_rank is not None and current_rank >= three_days_ago_rank:
        task.status = '효과없음'

    # 6일 전 대비
    if days_since_start >= 6 and six_days_ago_rank is not None and current_rank >= six_days_ago_rank:
        task.status = '환불권장'

    # 트래픽 권장 로직
    if task.status not in ['굿굿', '환불권장']:
        if 6 < current_rank <= 40:
            if three_days_ago_rank and (three_days_ago_rank - current_rank) < 5:
                task.needs_attention = True
            else:
                task.needs_attention = False
        else:
            task.needs_attention = False
    else:
        task.needs_attention = False

    # --------------------------
    # 추가 로직 1) 검색량 < 2만 & 현재 TOP6 => '키워드변경'
    # --------------------------
    monthly_volume = get_monthly_volume(task)
    if monthly_volume < 20000 and current_zone == 'TOP6':
        task.status = '키워드변경'

    # --------------------------
    # 추가 로직 2) 최근 7일 매출 감소 => '효과없음'
    # (키워드변경보다 우선시할지, 아니면 키워드변경이 우선인지 정책 결정 필요)
    # 여기서는 매출 감소가 더 우선이라고 가정 => 덮어씌운다
    # --------------------------
    if is_recent_sales_decreasing(task):
        task.status = '효과없음'

    task.save()