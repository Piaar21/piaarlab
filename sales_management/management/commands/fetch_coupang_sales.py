import os
import re
import logging
import decimal
import pandas as pd
import asyncio
from datetime import date, timedelta, datetime

from django.core.management.base import BaseCommand
from django.conf import settings
from decouple import config

from playwright.async_api import async_playwright

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
    help = "쿠팡 윙에서 입력받은 날짜 범위로 엑셀 다운로드 & DB 저장 (Playwright Async API 버전)"

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
        self.download_dir = download_dir  # 인스턴스 변수에 저장하여 set_date_field에서 사용

        # 비동기 함수 실행
        asyncio.run(self.login_and_download_coupang(download_dir, start_dt, end_dt))
        self.parse_and_store_to_db(download_dir)
        logger.info("[완료] fetch_coupang_sales 명령이 끝났습니다.")

    async def login_and_download_coupang(self, download_dir, start_d, end_d):
        COUPANG_ID = config('COUPANG_ID', default=None)
        COUPANG_PW = config('COUPANG_PW', default=None)
        NAVER_MAIL_ID = config('NAVER_MAIL_ID', default=None)
        NAVER_MAIL_PW = config('NAVER_MAIL_PW', default=None)
        
        async with async_playwright() as p:
            # browser = await p.chromium.launch(
            #     headless=True,
            #     args=["--headless", "--disable-gpu", "--disable-software-rasterizer", "--no-sandbox"]
            # )
            browser = await p.chromium.launch(
                headless=False,  # headed 모드로 실행
                args=["--disable-gpu", "--disable-software-rasterizer", "--no-sandbox"]
            )
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                # (B) 쿠팡 로그인
                logger.info("Navigating to 로그인 페이지...")
                await page.goto("https://wing.coupang.com/")
                await page.screenshot(path=os.path.join(self.download_dir, "01_login_page.png"))
                await page.wait_for_timeout(500)
                
                await page.fill("#username", COUPANG_ID)
                await page.fill("#password", COUPANG_PW)
                await page.screenshot(path=os.path.join(self.download_dir, "02_filled_credentials.png"))
                await page.click("#kc-login")
                await page.wait_for_timeout(500)
                await page.screenshot(path=os.path.join(self.download_dir, "03_after_kc-login.png"))
                
                # 2FA가 필요한지 여부 체크 (요소 기반)
                try:
                    await page.wait_for_selector("#btnEmail", timeout=5000)
                    logger.info("2FA 화면 감지: '#btnEmail' 요소 발견")
                    
                    # 2FA 페이지 스크린샷 및 HTML 로그
                    html_content = await page.content()
                    logger.info("===== 2FA Page HTML Start =====")
                    logger.info(html_content)
                    logger.info("===== 2FA Page HTML End =====")
                    await page.screenshot(path=os.path.join(self.download_dir, "04_2fa_page.png"))
                    
                    # "이메일로 인증하기" 버튼 클릭 - id "#btnEmail" 사용
                    await page.click("#btnEmail")
                    logger.info("이메일 인증하기 버튼(#btnEmail) 클릭 완료.")
                    await page.wait_for_timeout(1000)
                    await page.screenshot(path=os.path.join(self.download_dir, "05_after_btnEmail_click.png"))
                    
                    # 네이버 메일을 통해 2FA 인증번호 이메일 확인
                    logger.info("네이버 메일로 이동하여 2FA 인증번호 이메일 확인을 시작합니다.")
                    mail_page = await context.new_page()
                    await mail_page.goto("https://mail.naver.com/v2/folders/-1")
                    await mail_page.wait_for_timeout(1000)
                    
                    # 네이버 메일 페이지 로그인 전 스크린샷
                    await mail_page.screenshot(path=os.path.join(self.download_dir, "06_naver_mail_before_login.png"))
                    
                    # 네이버 메일 로그인: 아이디, 비밀번호 입력 (입력 필드는 input 태그로 수정)
                    await mail_page.fill("input#input_item_id", NAVER_MAIL_ID)
                    await mail_page.fill("input#input_item_pw", NAVER_MAIL_PW)
                    await mail_page.screenshot(path=os.path.join(self.download_dir, "07_naver_mail_filled.png"))
                    logger.info("네이버 메일 로그인 정보 입력 완료.")
                    
                    # 로그인 버튼 클릭 (셀렉터는 실제 페이지에 맞게 수정 필요)
                    await mail_page.click("button[type='submit']")
                    logger.info("네이버 메일 로그인 버튼 클릭 완료.")
                    await mail_page.wait_for_load_state("networkidle")
                    await mail_page.wait_for_timeout(3000)
                    await mail_page.screenshot(path=os.path.join(self.download_dir, "08_naver_mail_after_login.png"))
                    
                    # "[쿠팡] 이메일 인증번호가 도착하였습니다." 메일 클릭
                    await mail_page.wait_for_selector('[aria-label*="[쿠팡] 이메일 인증번호가 도착하였습니다."]', timeout=10000)
                    await mail_page.click('[aria-label*="[쿠팡] 이메일 인증번호가 도착하였습니다."]')
                    logger.info("2FA 인증번호 이메일 선택 완료.")
                    await mail_page.wait_for_timeout(3000)
                    await mail_page.screenshot(path=os.path.join(self.download_dir, "09_naver_mail_after_email_click.png"))
                    
                    # 확인 버튼 클릭 전, 이메일 페이지의 HTML 로그 출력
                    email_html = await mail_page.content()
                    logger.info("===== Naver Mail 2FA Email Page HTML Start =====")
                    logger.info(email_html)
                    logger.info("===== Naver Mail 2FA Email Page HTML End =====")
                    
                    # 여기서 이후 확인 버튼 클릭 전까지 멈춤.
                    
                except Exception as e:
                    logger.info("2FA 화면이 감지되지 않았거나 오류 발생: " + str(e))
                    await page.screenshot(path=os.path.join(self.download_dir, "2fa_error.png"))

                # (C) 대시보드 이동
                logger.info("Navigating to 대시보드 페이지...")
                await page.goto("https://wing.coupang.com/seller/notification/metrics/dashboard")
                await page.wait_for_timeout(500)
                dashboard_screenshot = os.path.join(self.download_dir, "dashboard.png")
                await page.screenshot(path=dashboard_screenshot)
                logger.info(f"Dashboard screenshot saved as '{dashboard_screenshot}'")
                dashboard_html = await page.content()
                logger.debug("Dashboard page HTML:\n" + dashboard_html)

                current = start_d
                loop_index = 0

                while current <= end_d:
                    date_str = current.strftime("%Y-%m-%d")
                    logger.info(f"[다운로드] 처리 날짜: {date_str}")

                    if loop_index == 0:
                        await self.set_date_field(page, "#dateStart", date_str)
                        await self.set_date_field(page, "#dateEnd", date_str)
                    else:
                        await self.set_date_field(page, "#dateEnd", date_str)
                        await self.set_date_field(page, "#dateStart", date_str)

                    await page.wait_for_timeout(1000)

                    download_button = await page.wait_for_selector("#download-product-info", timeout=10000)
                    await page.evaluate("element => element.scrollIntoView(true)", download_button)
                    await page.wait_for_timeout(500)

                    async with page.expect_download(timeout=8000) as download_info:
                        await page.evaluate("element => element.click()", download_button)
                        logger.info(f"{date_str} 다운로드 버튼 클릭 시도")
                    download = await download_info.value
                    target_file = os.path.join(download_dir, download.suggested_filename)
                    await download.save_as(target_file)
                    logger.info(f"{date_str} 파일 저장: {target_file}")
                    await page.wait_for_timeout(5000)

                    current += timedelta(days=1)
                    loop_index += 1

            except Exception as e:
                logger.exception("쿠팡 다운로드 중 오류:")
            finally:
                await context.close()
                await browser.close()

    async def set_date_field(self, page, selector, date_str):
        try:
            logger.info(f"Waiting for selector '{selector}' to be visible...")
            await page.wait_for_selector(selector, state="visible", timeout=30000)
        except Exception as e:
            logger.exception(f"Timeout waiting for selector {selector}: {e}")
            # 스크린샷과 HTML 기록 후 에러 재발생
            error_path = os.path.join(self.download_dir, "error_selector.png")
            await page.screenshot(path=error_path)
            logger.info(f"Error screenshot saved as '{error_path}'")
            html_error = await page.content()
            logger.debug("Page HTML at error:\n" + html_error)
            raise

        # 스크린샷 찍기
        debug_path = os.path.join(self.download_dir, "debug.png")
        await page.screenshot(path=debug_path)
        logger.info(f"Screenshot saved as '{debug_path}' for debugging before filling {selector}.")

        # 강제 입력 시도 (필요하면 force=True 옵션 추가 가능)
        await page.fill(selector, date_str)
        await page.evaluate("document.activeElement.blur()")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(200)
        try:
            await page.click("body", position={"x": 10, "y": 10})
        except Exception as e:
            logger.warning(f"body 클릭 실패: {e}")
        await page.wait_for_timeout(500)
        actual_val = await page.evaluate(f"document.querySelector('{selector}').value")
        logger.info(f"[set_date_field] {selector} → {date_str}, 실제 입력값: {actual_val}")

    def parse_and_store_to_db(self, download_dir):
        file_list = os.listdir(download_dir)
        for filename in file_list:
            if filename.lower().endswith((".xls", ".xlsx")):
                file_path = os.path.join(download_dir, filename)
                logger.info(f"[엑셀 파싱] {filename}")

                try:
                    df = pd.read_excel(file_path, dtype={"옵션ID": str})
                    logger.info(f"[엑셀 파싱] 컬럼: {df.columns.tolist()}")
                except Exception as e:
                    logger.warning(f"[{filename}] 엑셀 읽기 실패: {e}")
                    continue

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
                    if str(row.get("노출상품ID", "")).strip() == "합 계":
                        logger.info(f"[{filename}] 행({idx}) Summary row detected, skipping: {row.to_dict()}")
                        continue

                    if pd.isna(row["노출상품ID"]) or pd.isna(row["순 판매 금액(전체 거래 금액 - 취소 금액)"]):
                        logger.info(f"[{filename}] 행({idx}) 필수 데이터 누락 → 스킵: {row.to_dict()}")
                        continue

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

                    raw_item_name = str(row["옵션명"])
                    if "," in raw_item_name:
                        parts = raw_item_name.split(",", 1)
                        product_str = parts[0].strip()
                        option_str = parts[1].strip()
                    else:
                        product_str = raw_item_name
                        option_str = None

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