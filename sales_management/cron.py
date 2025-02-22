import logging
from datetime import date, timedelta
from django.core.management import call_command

logger = logging.getLogger(__name__)

def fetch_coupang_sales_daily():
    """
    매일 새벽(06:00)에 '어제 날짜'에 대한 매출 업데이트
    """
    # 전날
    yesterday = date.today() - timedelta(days=1)
    start_str = yesterday.strftime('%Y-%m-%d')
    end_str   = start_str  # 단 하루(어제)

    logger.info(f"[CRON] 전날 쿠팡 매출 업데이트: {start_str}")
    # Management Command 호출
    call_command('fetch_coupang_sales', start=start_str, end=end_str)
    logger.info("[CRON] 완료!")