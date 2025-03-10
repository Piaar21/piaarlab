# naver_update_logic.py

import json
import time
import datetime
import logging
from decouple import config
from django.conf import settings
from .views import fetch_naver_sales, update_naver_daily_sales, create_stat_report, get_stat_report, download_report, save_naver_ads_report

logger = logging.getLogger(__name__)

NAVER_ACCOUNTS = config("NAVER_ACCOUNTS", default="[]", cast=json.loads)
NAVER_AD_ACCESS = config(settings, "NAVER_AD_ACCESS", None)
NAVER_AD_SECRET = config(settings, "NAVER_AD_SECRET", None)
CUSTOMER_ID = config(settings, "CUSTOMER_ID", None)

def update_naver_sales_logic(start_str, end_str):
    """
    start_str, end_str: 'YYYY-MM-DD' 형식의 문자열
    """
    from datetime import datetime
    start_dt = datetime.strptime(start_str, '%Y-%m-%d')
    end_dt   = datetime.strptime(end_str, '%Y-%m-%d')

    print("update_naver_sales_logic 호출됨: start=%s, end=%s" % (start_dt, end_dt))
    logger.debug("update_naver_sales_logic 호출됨: start=%s, end=%s", start_dt, end_dt)
    for account_info in NAVER_ACCOUNTS:
        try:
            logger.info("[DEBUG] 호출: fetch_naver_sales for account [%s] with start=%s end=%s",
                        account_info['names'], start_dt, end_dt)
            result = fetch_naver_sales(account_info, start_dt, end_dt)

            if isinstance(result, dict):
                orders = result.get("data", [])
            elif isinstance(result, list):
                orders = result
            else:
                orders = []

            if orders:
                logger.info("[DEBUG] update_naver_daily_sales 호출: orders len=%d for account [%s]",
                            len(orders), account_info['names'])
                update_naver_daily_sales(orders, account_info)
            else:
                logger.info("[DEBUG] update_naver_daily_sales 생략: 업데이트할 주문 없음 for account [%s]",
                            account_info['names'])
        except Exception as e:
            logger.error("[ERROR] 네이버 매출 업데이트 중 예외 발생 for account [%s]",
                         account_info['names'], exc_info=True)

def update_naver_ads_report_logic(raw_start, raw_end):
    from datetime import datetime, timedelta
    

    if not all([NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID]):
        logger.error("네이버 광고 API 설정이 누락되었습니다.")
        return

    try:
        start_date = datetime.strptime(raw_start, "%Y-%m-%d").date() if raw_start else datetime.now().date()
        end_date = datetime.strptime(raw_end, "%Y-%m-%d").date() if raw_end else datetime.now().date()
    except ValueError as ve:
        logger.error("날짜 파싱 에러 발생: %s", ve)
        start_date = datetime.now().date()
        end_date = datetime.now().date()

   
    current_date = start_date
    while current_date <= end_date:
        stat_dt_str = current_date.strftime("%Y%m%d")
        for report_tp in ["AD_DETAIL", "AD_CONVERSION_DETAIL"]:
            try:
                logger.info("%s 작업 시작 for %s", report_tp, stat_dt_str)
                stat_res = create_stat_report(report_tp, stat_dt_str)
                if not stat_res or "reportJobId" not in stat_res:
                    logger.warning("%s 생성 실패 for %s - stat_res: %s", report_tp, stat_dt_str, stat_res)
                    continue
                report_job_id = stat_res["reportJobId"]
                time.sleep(5)  # 대기
                detail_stat = get_stat_report(report_job_id)
                if not detail_stat:
                    logger.warning("%s 조회 실패 for %s with report_job_id: %s", report_tp, stat_dt_str, report_job_id)
                    continue
                download_url = detail_stat.get("downloadUrl")
                file_name = f"{stat_dt_str}_{report_tp}.csv"
                if download_url:
                    saved_file = download_report(download_url, file_name)
                    if saved_file:
                        logger.info("%s 다운로드 성공 for %s, saved_file: %s", report_tp, stat_dt_str, saved_file)
                    else:
                        logger.error("%s 다운로드 실패 for %s", report_tp, stat_dt_str)
                else:
                    logger.info("%s downloadUrl 미존재 for %s", report_tp, stat_dt_str)
            except Exception as e:
                logger.error("[ERROR] %s 처리 중 예외 발생 for %s", report_tp, stat_dt_str, exc_info=True)
        current_date += timedelta(days=1)

    try:
        logger.info("CSV 파일 파싱 및 DB 업데이트 시작")
        save_naver_ads_report()
        logger.info("CSV 파일 파싱 및 DB 업데이트 완료")
    except Exception as e:
        logger.error("CSV 파일 파싱 및 DB 업데이트 중 예외 발생", exc_info=True)
