import os
import re
import logging
import decimal
import pandas as pd
import asyncio
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand
from django.conf import settings
from decouple import config

from playwright.async_api import async_playwright

from sales_management.models import CoupangAdsReport

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "쿠팡 광고페이지에서 날짜 범위(일별)로 엑셀 다운로드 후 DB 저장 (엑셀 삭제, Playwright Async API 버전)"

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, help="시작일(YYYY-MM-DD)")
        parser.add_argument('--end',   type=str, help="종료일(YYYY-MM-DD)")

    def handle(self, *args, **options):
        start_str = options.get('start')
        end_str = options.get('end')

        if start_str and end_str:
            try:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
                end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
            except ValueError:
                logger.warning("날짜 파싱 실패, 기본값 사용")
                start_dt = date(2025, 2, 9)
                end_dt = date(2025, 2, 9)
        else:
            start_dt = date(2025, 2, 9)
            end_dt = date(2025, 2, 9)

        logger.info(f"[fetch_coupang_ads] {start_dt} ~ {end_dt}")

        download_dir = os.path.join(settings.BASE_DIR, "downloads")
        os.makedirs(download_dir, exist_ok=True)

        asyncio.run(self.login_and_download_ads(download_dir, start_dt, end_dt))
        self.parse_and_store_ads_reports(download_dir)
        logger.info("[완료] fetch_coupang_ads 명령이 끝났습니다.")

    async def login_and_download_ads(self, download_dir, start_d, end_d):
        COUPANG_ID = config('COUPANG_ID', default=None)
        COUPANG_PW = config('COUPANG_PW', default=None)

        logger.info("Launching Chromium in headless mode: %s", True)
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--headless", "--disable-gpu", "--disable-software-rasterizer", "--no-sandbox"]
            )
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                # (A) 윙 로그인
                await page.goto("https://wing.coupang.com/")
                await page.wait_for_timeout(500)
                await page.fill("#username", COUPANG_ID)
                await page.fill("#password", COUPANG_PW)
                await page.click("#kc-login")
                await page.wait_for_timeout(1000)

                # (B) 광고 보고서 페이지 이동
                await page.goto("https://advertising.coupang.com/marketing-reporting/billboard/reports/pa")
                await page.wait_for_timeout(1000)

                # (B-1) 재인증 버튼 확인
                try:
                    reauth_btn = await page.wait_for_selector('//a[@href="/user/wing/authorization"]', timeout=3000)
                    if reauth_btn:
                        await reauth_btn.click()
                        await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.info("재인증 버튼 없음/이미 로그인")

                # (C) '기간 설정' 라디오 클릭
                try:
                    period_label = await page.wait_for_selector(
                        '//label[contains(@class,"ant-radio-wrapper") and .//span[text()="기간 설정"]]',
                        timeout=5000
                    )
                    await page.evaluate("element => element.click()", period_label)
                    await page.wait_for_timeout(1000)
                    classes = await period_label.get_attribute("class")
                    if "ant-radio-wrapper-checked" in classes:
                        logger.info("'기간 설정' 라디오 체크됨!")
                    else:
                        logger.warning("'기간 설정' 클릭 후 체크 안됨?")
                except Exception as e:
                    logger.exception("'기간 설정' 라벨 클릭 실패:")

                # (C-1) RangePicker 열기 및 날짜 선택
                date_picker = await page.wait_for_selector("div.ant-picker-input", timeout=10000)
                await date_picker.click()
                await page.wait_for_timeout(1000)

                start_xpath = f'//td[@title="{start_d.strftime("%Y-%m-%d")}"]'
                end_xpath = f'//td[@title="{end_d.strftime("%Y-%m-%d")}"]'

                try:
                    start_elem = await page.wait_for_selector(start_xpath, timeout=5000)
                    await start_elem.click()
                    await page.wait_for_timeout(500)
                except Exception as e:
                    logger.exception(f"{start_d} 클릭 실패:")

                try:
                    end_elem = await page.wait_for_selector(end_xpath, timeout=5000)
                    await end_elem.click()
                    await page.wait_for_timeout(500)
                except Exception as e:
                    logger.exception(f"{end_d} 클릭 실패:")

                try:
                    ok_btn = await page.wait_for_selector("button.ant-picker-ok", timeout=5000)
                    await ok_btn.click()
                    await page.wait_for_timeout(1000)
                    logger.info(f"RangePicker에 {start_d} ~ {end_d} 설정 완료.")
                except:
                    logger.info("확인 버튼이 없거나 이미 닫힘.")

                # (D) "일별" 라디오 선택
                try:
                    daily_label = await page.wait_for_selector(
                        '//label[contains(@class,"ant-radio-wrapper") and .//span[text()="일별"]]',
                        timeout=5000
                    )
                    await page.evaluate("element => element.click()", daily_label)
                    await page.wait_for_timeout(1000)
                    logger.info("'일별' 라디오 체크 완료.")
                except Exception as e:
                    logger.exception("'일별' 라벨 클릭 실패:")

                # (E) 캠페인 전체선택 -> 확인 버튼 클릭
                try:
                    camp_btn = await page.wait_for_selector("button.campaign-picker-dropdown-btn", timeout=5000)
                    await camp_btn.click()
                    await page.wait_for_timeout(1000)
                    select_all_label = await page.wait_for_selector(
                        '//label[contains(@class,"ant-checkbox-wrapper") and .//span[text()="전체선택"]]',
                        timeout=10000
                    )
                    await select_all_label.click()
                    await page.wait_for_timeout(1000)
                    confirm_btn = await page.wait_for_selector(
                        'button.ant-btn.ant-btn-primary.confirm-button',
                        timeout=10000
                    )
                    await confirm_btn.click()
                    await page.wait_for_timeout(1000)
                except Exception as e:
                    logger.exception("캠페인 전체선택 과정 실패:")

                # (E-1) "캠페인 > 광고그룹 > 상품 > 키워드" 라디오 선택
                try:
                    radio_label = await page.wait_for_selector(
                        '//label[contains(@class,"ant-radio-wrapper") and .//span[text()="캠페인 > 광고그룹 > 상품 > 키워드"]]',
                        timeout=5000
                    )
                    await page.evaluate("element => element.click()", radio_label)
                    await page.wait_for_timeout(1000)
                    label_class = await radio_label.get_attribute("class")
                    if "ant-radio-wrapper-checked" in label_class:
                        logger.info("‘캠페인 > 광고그룹 > 상품 > 키워드’ 라디오 체크됨!")
                    else:
                        logger.warning("라디오 클릭 후 checked 안됨?")
                except Exception as e:
                    logger.exception("‘캠페인 > 광고그룹 > 상품 > 키워드’ 라벨 클릭 실패:")

                # (F) 보고서 만들기 버튼 클릭
                try:
                    create_btn = await page.wait_for_selector(
                        '//button[contains(@class,"ant-btn-primary") and contains(., "보고서 만들기")]',
                        timeout=10000
                    )
                    await page.evaluate("element => element.click()", create_btn)
                    logger.info("보고서 만들기 버튼 클릭 완료.")
                    await page.wait_for_timeout(3000)
                except Exception as e:
                    logger.exception("보고서 만들기 버튼 찾기/클릭 실패:")

                # (G) row-index=0 행 대기 및 상태 확인 후 다운로드 진행
                try:
                    row_xpath = '//div[@role="row" and @row-index="0"]'
                    row_elem = await page.wait_for_selector(row_xpath, timeout=30000)
                    logger.info("row-index=0 행을 찾았습니다.")

                    try:
                        status_cell = await row_elem.query_selector('.//div[@role="gridcell" and @col-id="status"]//div[contains(text(),"생성중")]')
                        if status_cell:
                            logger.info("row-index=0 행의 상태가 '생성중'임을 확인했습니다.")
                    except Exception as e:
                        logger.warning("row-index=0 행이 '생성중' 상태가 아닙니다. 혹시 이미 '생성 완료'인가요?")

                    await page.wait_for_function(
                        f'''() => document.evaluate('{row_xpath}//div[@role="gridcell" and @col-id="status"]//div', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue && 
                        document.evaluate('{row_xpath}//div[@role="gridcell" and @col-id="status"]//div', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue.innerText.includes("생성 완료")''',
                        timeout=120000
                    )
                    logger.info("row-index=0 행이 '생성 완료'로 변경되었습니다.")

                    await page.evaluate("element => element.scrollIntoView(true)", row_elem)
                    await page.wait_for_timeout(1000)
                    download_btn = await row_elem.query_selector("xpath=.//button[contains(@class,'ant-btn-primary') and .//span[text()='다운로드']]")
                    if download_btn:
                        await page.evaluate("element => element.scrollIntoView(true)", download_btn)
                        await page.wait_for_timeout(1000)
                        async with page.expect_download(timeout=15000) as download_info:
                            await download_btn.click()
                        download = await download_info.value
                        target_file = os.path.join(download_dir, download.suggested_filename)
                        await download.save_as(target_file)
                        logger.info("row-index=0 행의 다운로드 버튼 클릭 완료. 파일 저장: " + target_file)
                        await page.wait_for_timeout(5000)
                    else:
                        logger.warning("다운로드 버튼을 찾지 못했습니다.")
                except Exception as e:
                    logger.exception("다운로드 버튼 클릭 실패:")

            except Exception as e:
                logger.exception("광고 다운로드 중 오류:")
            finally:
                await context.close()
                await browser.close()

    def parse_and_store_ads_reports(self, download_dir):
        excel_files = [f for f in os.listdir(download_dir)
                       if f.lower().endswith((".xls", ".xlsx"))]
        if not excel_files:
            logger.info(f"[{download_dir}] 엑셀 파일이 없습니다.")
            return

        for fname in excel_files:
            fpath = os.path.join(download_dir, fname)
            logger.info(f"[엑셀 파싱] {fname}")

            try:
                df = pd.read_excel(fpath)
                logger.info(f"{fname} → 컬럼: {df.columns.tolist()}")
            except Exception as e:
                logger.warning(f"[{fname}] 엑셀 읽기 실패: {e}")
                continue

            saved_count = 0
            row_count = len(df)
            logger.info(f"→ 총 {row_count}행 (Header 제외)")

            for i, row in df.iterrows():
                if row.isna().all():
                    logger.debug(f"[{fname} row={i}] 전체 NaN → 스킵")
                    continue

                logger.debug(f"[{fname} row={i}] 원본 row = {row.to_dict()}")

                raw_date = row.get("날짜", None)
                parsed_date = self.parse_excel_date(raw_date)
                if not parsed_date:
                    logger.debug(f"[{fname} row={i}] 날짜 파싱 실패(raw_date={raw_date}) → 스킵")
                    continue

                ad_type_val = self.to_str(row.get("광고유형", ""))
                campaign_id_val = self.to_str(row.get("캠페인 ID", ""))
                campaign_name_val = self.to_str(row.get("캠페인명", ""))
                ad_group_val = self.to_str(row.get("광고그룹", ""))

                executed_product_name_val = self.to_str(row.get("광고집행 상품명", ""))
                product_name_val, option_name_val = self.split_product_option(executed_product_name_val)
                executed_option_id_val = self.to_str(row.get("광고집행 옵션ID", ""))

                converting_product_name_val = self.to_str(row.get("광고전환매출발생 상품명", ""))
                converting_option_id_val = self.to_str(row.get("광고전환매출발생 옵션ID", ""))
                ad_placement_val = self.to_str(row.get("광고 노출 지면", ""))

                impressions_val = self.to_int(row.get("노출수", 0))
                clicks_val      = self.to_int(row.get("클릭수", 0))
                ad_spend_val    = self.to_decimal(row.get("광고비", 0))
                ctr_val         = self.parse_percent(row.get("클릭률", "0"))
                orders_val      = self.to_int(row.get("총 주문수(1일)", 0))
                sold_qty_val    = self.to_int(row.get("총 판매수량(1일)", 0))
                sales_amt_val   = self.to_decimal(row.get("총 전환매출액(1일)", 0))
                roas_val        = self.to_decimal(row.get("총광고수익률(1일)", 0))

                logger.debug(
                    f"[{fname} row={i}] date={parsed_date}, ad_type={ad_type_val}, "
                    f"camp_id={campaign_id_val}, camp_name={campaign_name_val}, "
                    f"impressions={impressions_val}, clicks={clicks_val}, "
                    f"ad_spend={ad_spend_val}, ctr={ctr_val}, orders={orders_val}, "
                    f"sold_qty={sold_qty_val}, sales_amt={sales_amt_val}, roas={roas_val}"
                )

                try:
                    rec = CoupangAdsReport(
                        date=parsed_date,
                        ad_type=ad_type_val,
                        campaign_id=campaign_id_val,
                        campaign_name=campaign_name_val,
                        ad_group=ad_group_val,
                        executed_product_name=executed_product_name_val,
                        product_name=product_name_val,
                        option_name=option_name_val,
                        executed_option_id=executed_option_id_val,
                        converting_product_name=converting_product_name_val,
                        converting_option_id=converting_option_id_val,
                        ad_placement=ad_placement_val,
                        impressions=impressions_val,
                        clicks=clicks_val,
                        ad_spend=ad_spend_val,
                        ctr=ctr_val,
                        orders=orders_val,
                        sold_quantity=sold_qty_val,
                        sales_amount=sales_amt_val,
                        roas=roas_val
                    )
                    rec.save()
                    saved_count += 1
                except Exception as ex:
                    logger.warning(f"[{fname} row={i}] DB 저장 실패: {ex}")

            logger.info(f"[{fname}] AdsReport 저장 완료: {saved_count}건")
            os.remove(fpath)
            logger.info(f"[파일 삭제] {fname}")

    def split_product_option(self, full_name_str):
        if not full_name_str:
            return ("", "")
        parts = full_name_str.split(",", 1)
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
        else:
            return (full_name_str.strip(), "")

    def parse_excel_date(self, raw):
        if raw is None or pd.isna(raw):
            return None

        if isinstance(raw, datetime):
            return raw.date()

        if isinstance(raw, (int, float)):
            raw = str(int(raw))

        if isinstance(raw, str):
            raw = raw.strip()
            if len(raw) == 8 and raw.isdigit():
                try:
                    return datetime.strptime(raw, "%Y%m%d").date()
                except:
                    pass

            for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except:
                    pass

            try:
                return datetime.strptime(raw, "%Y년 %m월 %d일").date()
            except:
                pass

        return None

    def parse_percent(self, val):
        from decimal import Decimal
        if pd.isna(val):
            return Decimal("0.00")
        if isinstance(val, str):
            tmp = val.strip().replace("%", "").replace(",", "")
            if not tmp:
                return Decimal("0.00")
            try:
                return Decimal(tmp)
            except:
                return Decimal("0.00")
        try:
            return Decimal(str(val))
        except:
            return Decimal("0.00")

    def to_str(self, val):
        if pd.isna(val):
            return ""
        return str(val).strip()

    def to_int(self, val):
        if pd.isna(val):
            return 0
        try:
            return int(val)
        except:
            return 0

    def to_decimal(self, val):
        from decimal import Decimal
        if pd.isna(val):
            return Decimal("0.00")
        if isinstance(val, str):
            val = val.strip().replace(",", "").replace("%", "")
        try:
            return Decimal(str(val))
        except:
            return Decimal("0.00")