# coupang_report_selenium_debug.py
import os
import time
import logging
from datetime import date, timedelta
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 로깅 설정: INFO 레벨 (중요 정보와 에러만 출력)
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(asctime)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def set_date_field(driver, selector, date_str):
    # JavaScript로 날짜 필드의 value를 강제로 지정하고, input/change/blur 이벤트 발생
    script = (
        "var elem = document.querySelector(arguments[0]); "
        "if (elem) { "
        "  elem.value = arguments[1]; "
        "  elem.dispatchEvent(new Event('input', { bubbles: true })); "
        "  elem.dispatchEvent(new Event('change', { bubbles: true })); "
        "  elem.dispatchEvent(new Event('blur', { bubbles: true })); "
        "} else { "
        "  console.error('No element found for selector: ' + arguments[0]); "
        "}"
    )
    driver.execute_script(script, selector, date_str)
    logger.info(f"날짜 필드 {selector} 값을 {date_str}으로 설정 후 이벤트 발생.")

def main():
    load_dotenv()
    COUPANG_ID = os.getenv("COUPANG_ID")
    COUPANG_PW = os.getenv("COUPANG_PW")
    logger.info("환경변수 로드 완료.")

    # 다운로드 경로 설정 (현재 디렉토리의 downloads 폴더)
    download_dir = os.path.abspath("./downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        logger.info(f"다운로드 폴더 생성: {download_dir}")
    else:
        logger.info(f"다운로드 폴더 존재: {download_dir}")

    # Chrome 옵션 설정
    options = webdriver.ChromeOptions()
    # headless 모드 사용 시 아래 주석을 해제하세요.
    # options.add_argument("headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)
    logger.info("Chrome 옵션 및 다운로드 환경설정 완료.")

    # Chrome 드라이버 시작 및 CDP를 통한 다운로드 행동 설정
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": download_dir
    })
    logger.info("CDP를 통해 다운로드 행동 설정 완료.")

    try:
        # (2) 쿠팡 윙 로그인
        logger.info("쿠팡 윙 로그인 페이지로 이동.")
        driver.get("https://wing.coupang.com/")
        time.sleep(1)  # 페이지 로딩 대기

        logger.info("로그인 폼 입력 시작.")
        # 로그인 폼의 구조가 변경되었을 수 있으므로, 최신 선택자를 확인하세요.
        username_field = driver.find_element(By.CSS_SELECTOR, "#username")
        username_field.clear()
        username_field.send_keys(COUPANG_ID)
        logger.info("아이디 입력 완료.")
        
        password_field = driver.find_element(By.CSS_SELECTOR, "#password")
        password_field.clear()
        password_field.send_keys(COUPANG_PW)
        logger.info("비밀번호 입력 완료.")
        
        driver.find_element(By.CSS_SELECTOR, "#kc-login").click()
        logger.info("로그인 버튼 클릭.")
        time.sleep(1)  # 로그인 후 대기

        # (3) 대시보드 이동
        logger.info("대시보드 페이지로 이동.")
        driver.get("https://wing.coupang.com/seller/notification/metrics/dashboard")
        time.sleep(1)
        logger.info("대시보드 페이지 로딩 완료.")

        # (4) 날짜별 다운로드 처리 (예: 2025-02-11 ~ 2025-02-12)
        start_d = date(2025, 2, 9)
        end_d = date(2025, 2, 12)
        current = start_d

        while current <= end_d:
            date_str = current.strftime("%Y-%m-%d")
            logger.info(f"처리 중인 날짜: {date_str}")

            # 날짜 필드 강제 업데이트 (종료일과 시작일 모두)
            set_date_field(driver, "#dateEnd", date_str)
            set_date_field(driver, "#dateStart", date_str)
            time.sleep(1)

            # 스크린샷 저장 (디버깅용)
            before_screenshot = f"debug_{date_str}_before_download.png"
            driver.save_screenshot(before_screenshot)
            logger.info(f"다운로드 전 스크린샷 저장: {before_screenshot}")

            # 다운로드 버튼 클릭 (WebDriverWait + 스크롤 + JavaScript 클릭 fallback)
            try:
                download_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#download-product-info"))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", download_button)
                time.sleep(0.5)
                try:
                    download_button.click()
                    logger.info(f"다운로드 버튼 클릭 성공: {date_str}")
                except Exception as e:
                    logger.error(f"일반 클릭 실패: {e} → JavaScript 클릭 시도")
                    driver.execute_script("arguments[0].click();", download_button)
                    logger.info(f"JavaScript 클릭 성공: {date_str}")
            except Exception as e:
                logger.error(f"{date_str} 다운로드 버튼 찾기 실패: {e}")

            # 파일 다운로드 완료 대기 (여기서는 5초 대기)
            time.sleep(5)
            logger.info("다운로드 완료 대기 5초.")



            current += timedelta(days=1)

        logger.info("모든 날짜 처리 완료.")

    except Exception as e:
        logger.exception("예상치 못한 오류 발생:")
    finally:
        driver.quit()
        logger.info("드라이버 종료 완료.")

if __name__ == "__main__":
    main()