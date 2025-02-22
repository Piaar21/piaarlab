import os
import re
import time
import logging
import decimal
import pandas as pd
from datetime import date, timedelta, datetime

from django.core.management.base import BaseCommand
from django.conf import settings
from decouple import config

from playwright.sync_api import sync_playwright

from sales_management.models import CoupangDailySales

logger = logging.getLogger(__name__)

# 헬퍼 함수: 딕셔너리의 모든 키를 문자열로 변환 (JSON 직렬화 문제 해결용)
def convert_keys(obj):
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            new_key = str(k)
            new_dict[new_key] = convert_keys(v)
        return new_dict
    elif isinstance(obj, list):
        return [convert_keys(item) for item in obj]
    else:
        return obj

class Command(BaseCommand):
    help = "쿠팡 윙에서 입력받은 날짜 범위로 엑셀 다운로드 & DB 저장 (Playwright 버전)"

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, help="시작일(YYYY-MM-DD)")
        parser.add_argument('--end',   type=str, help="종료일(YYYY-MM-DD)")

    def handle(self, *args, **options):
        # 1) 인자 파싱
        start_str = options.get('start')
        end_str   = options.get('end')
        if start_str and end_str:
            try:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
                end_dt   = datetime.strptime(end_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning(f"날짜 파싱 실패 start=[{start_str}], end=[{end_str}] → 기본값 사용")
                start_dt = date(2025, 2, 1)
                end_dt   = date(2025, 2, 12)
        else:
            start_dt = date(2025, 2, 1)
            end_dt   = date(2025, 2, 12)

        logger.info(f"[fetch_coupang_sales] 시작~종료: {start_dt} ~ {end_dt}")

        download_dir = os.path.join(settings.BASE_DIR, "sales_management", "download")
        os.makedirs(download_dir, exist_ok=True)

        # (1) 다운로드
        self.login_and_download_coupang(download_dir, start_dt, end_dt)
        # (2) 파싱 & DB 저장 후 파일 삭제
        self.parse_and_store_to_db(download_dir)
        logger.info("[완료] fetch_coupang_sales 명령이 끝났습니다.")

    def login_and_download_coupang(self, download_dir, start_d, end_d):
        """인자로 받은 start_d, end_d 범위를 Playwright로 다운로드"""
        COUPANG_ID = config('COUPANG_ID', default=None)
        COUPANG_PW = config('COUPANG_PW', default=None)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            try:
                # (B) 로그인
                page.goto("https://wing.coupang.com/")
                page.wait_for_timeout(500)  # 0.5초 대기
                page.fill("#username", COUPANG_ID)
                page.fill("#password", COUPANG_PW)
                page.click("#kc-login")
                page.wait_for_timeout(500)

                # (C) 대시보드 이동
                page.goto("https://wing.coupang.com/seller/notification/metrics/dashboard")
                page.wait_for_timeout(500)

                current = start_d
                loop_index = 0

                while current <= end_d:
                    date_str = current.strftime("%Y-%m-%d")
                    logger.info(f"[다운로드] 처리 날짜: {date_str}")

                    if loop_index == 0:
                        # 첫 날짜: 시작일 → 종료일 순서
                        self.set_date_field(page, "#dateStart", date_str)
                        self.set_date_field(page, "#dateEnd", date_str)
                    else:
                        # 그 이후: 종료일 → 시작일 순서
                        self.set_date_field(page, "#dateEnd", date_str)
                        self.set_date_field(page, "#dateStart", date_str)

                    page.wait_for_timeout(1000)  # 1초 대기

                    # (D) 다운로드 버튼 선택 및 스크롤
                    download_button = page.wait_for_selector("#download-product-info", timeout=10000)
                    page.evaluate("element => element.scrollIntoView(true)", download_button)
                    page.wait_for_timeout(500)

                    # (E) 다운로드 버튼 클릭 및 다운로드 대기
                    with page.expect_download(timeout=8000) as download_info:
                        page.evaluate("element => element.click()", download_button)
                        logger.info(f"{date_str} 다운로드 버튼 클릭 시도")
                    download = download_info.value
                    target_file = os.path.join(download_dir, download.suggested_filename)
                    download.save_as(target_file)  # 파일을 원하는 폴더로 저장
                    logger.info(f"{date_str} 파일 저장: {target_file}")
                    page.wait_for_timeout(5000)  # 다운로드 완료 대기

                    current += timedelta(days=1)
                    loop_index += 1

            except Exception as e:
                logger.exception("쿠팡 다운로드 중 오류:")
            finally:
                context.close()
                browser.close()

    def set_date_field(self, page, selector, date_str):
        """
        날짜 필드에 값을 입력한 후 포커스를 강제로 제거하여 달력 UI가 제대로 반영되도록 합니다.
        """
        # 날짜 입력
        page.fill(selector, date_str)
        
        # 1. 현재 활성 요소에 blur() 호출
        page.evaluate("document.activeElement.blur()")
        page.wait_for_timeout(200)
        
        # 2. 키보드 Tab 키를 눌러 포커스를 이동시킵니다.
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        
        # 3. 페이지의 body 상단 좌측 (10,10) 위치를 클릭하여 확실히 포커스 제거 시도
        try:
            page.click("body", position={"x": 10, "y": 10})
        except Exception as e:
            logger.warning(f"body 클릭 실패: {e}")
        
        page.wait_for_timeout(500)
        actual_val = page.evaluate(f"document.querySelector('{selector}').value")
        logger.info(f"[set_date_field] {selector} → {date_str}, 실제 입력값: {actual_val}")

    def parse_and_store_to_db(self, download_dir):
        file_list = os.listdir(download_dir)
        for filename in file_list:
            if filename.lower().endswith((".xls", ".xlsx")):
                file_path = os.path.join(download_dir, filename)
                logger.info(f"[엑셀 파싱] {filename}")

                # (1) 엑셀 파일 읽기 (옵션ID 열은 문자열로 지정)
                df = pd.read_excel(file_path, dtype={"옵션ID": str})
                logger.info(f"[엑셀 파싱] 컬럼: {df.columns.tolist()}")

                # (2) 파일명에서 날짜 추출 (예: Statistics-20250212~20250212_(0).xlsx)
                date_from_filename = None
                match = re.search(r"Statistics-(\d{8})~(\d{8})", filename)
                if match:
                    start_str, end_str = match.group(1), match.group(2)
                    start_dt_parsed = datetime.strptime(start_str, "%Y%m%d").date()
                    end_dt_parsed = datetime.strptime(end_str, "%Y%m%d").date()
                    if start_dt_parsed == end_dt_parsed:
                        date_from_filename = start_dt_parsed
                    else:
                        logger.info(f"[{filename}] 날짜 범위가 다릅니다. 파일 건너뜁니다.")
                        continue
                if date_from_filename is None:
                    logger.error(f"[{filename}] 날짜 추출 실패. 파일명을 확인해주세요.")
                    continue  # 날짜 정보가 없으면 해당 파일 건너뜁니다.

                # (3) 엑셀 행 순회 및 DB 저장
                for idx, row in df.iterrows():
                    # 1. 합계 행(요약 행) 건너뛰기
                    if str(row.get("노출상품ID", "")).strip() == "합 계":
                        logger.info(f"[{filename}] 행({idx}) Summary row detected, skipping: {row.to_dict()}")
                        continue

                    # 2. 필수 컬럼 검사
                    if pd.isna(row["노출상품ID"]) or pd.isna(row["순 판매 금액(전체 거래 금액 - 취소 금액)"]):
                        logger.info(f"[{filename}] 행({idx}) 필수 데이터 누락 → 스킵: {row.to_dict()}")
                        continue

                    # 3. 아이템위너 비율(%) 처리
                    item_winner_ratio_raw = row.get("아이템위너 비율(%)", "0")
                    if pd.isna(item_winner_ratio_raw):
                        item_winner_ratio_raw = "0"
                    raw_ratio = str(item_winner_ratio_raw)
                    ratio_str = raw_ratio.replace('%', '').strip() or '0'
                    try:
                        item_winner_val = decimal.Decimal(ratio_str)
                    except decimal.InvalidOperation:
                        logger.info(f"'{raw_ratio}' → 숫자 변환 실패, 행({idx}) 스킵")
                        continue

                    # 4. 옵션명 쉼표 분리 → product_name, option_name
                    raw_item_name = str(row["옵션명"])
                    if "," in raw_item_name:
                        parts = raw_item_name.split(",", 1)
                        product_str = parts[0].strip()
                        option_str = parts[1].strip()
                    else:
                        product_str = raw_item_name
                        option_str = None

                    # 5. 기타 숫자형 필드 처리
                    try:
                        net_sales_val = int(row["순 판매 금액(전체 거래 금액 - 취소 금액)"])
                    except:
                        net_sales_val = 0
                    try:
                        total_trans_val = int(row["전체 거래 금액"])
                    except:
                        total_trans_val = 0
                    try:
                        total_cancel_val = int(row["총 취소 금액"])
                    except:
                        total_cancel_val = 0
                    try:
                        net_sold_items_val = int(row["순 판매 상품 수(전체 거래 상품 수 - 취소 상품 수)"])
                    except:
                        net_sold_items_val = 0
                    try:
                        total_trans_items_val = int(row["전체 거래 상품 수"])
                    except:
                        total_trans_items_val = 0
                    try:
                        total_cancel_items_val = int(row["총 취소 상품 수"])
                    except:
                        total_cancel_items_val = 0
                    try:
                        immediate_cancel_items_val = int(row["즉시 취소 상품 수"])
                    except:
                        immediate_cancel_items_val = 0

                    sku_str = str(row["옵션ID"])

                    record = CoupangDailySales(
                        displayed_product_id=row["노출상품ID"],
                        sku_id=sku_str,
                        item_name=raw_item_name,
                        product_name=product_str,
                        option_name=option_str,
                        delivery_label=row["상품타입"],
                        category_name=row["카테고리"],
                        item_winner_ratio=item_winner_val,
                        net_sales_amount=net_sales_val,
                        net_sold_items=net_sold_items_val,
                        total_transaction_amount=total_trans_val,
                        total_transaction_items=total_trans_items_val,
                        total_cancellation_amount=total_cancel_val,
                        total_cancelled_items=total_cancel_items_val,
                        immediate_cancellation_items=immediate_cancel_items_val,
                        date=date_from_filename,
                    )
                    try:
                        record.save()
                    except Exception as e:
                        logger.exception(f"DB 저장 실패, 행({idx}): {e}")

                os.remove(file_path)
                logger.info(f"[완료] DB 저장 후 파일 삭제: {filename}")