# api_clients.py

import asyncio
import aiohttp
import logging
import re
from django.contrib.auth.models import User
from .models import UserProfile
from asgiref.sync import async_to_sync
from decouple import config
from proxy_config import proxies

logger = logging.getLogger(__name__)

naver_client_id = config('NAVER_CLIENT_ID', default=None)
naver_client_secret = config('NAVER_CLIENT_SECRET', default=None)
ad_naver_customer_id = config('NAVER_AD_CUSTOMER_ID', default=None)
ad_naver_access_id = config('NAVER_AD_ACCESS', default=None)
ad_naver_client_secret = config('NAVER_CLIENT_SECRET', default=None)


def normalize_url(url):
    url = re.sub(r'^https?://(www\.)?', '', url)
    url = url.rstrip('/')
    return url

def extract_product_id(url):
    match = re.search(r'/products/(\d+)', url)
    if match:
        return match.group(1)
    return None

def convert_to_naver_url(product_id):
    return f'https://smartstore.naver.com/main/products/{product_id}'

async def fetch(session, url, headers, params, start, target_url, semaphore):
    async with semaphore:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                items = data.get('items')
                if not items:
                    return None

                for index, item in enumerate(items):
                    total_rank = start + index
                    item_link = item['link']
                    item_product_id = extract_product_id(item_link)
                    if item_product_id:
                        item_link = convert_to_naver_url(item_product_id)

                    if normalize_url(item_link) == normalize_url(target_url):
                        return total_rank
            else:
                logger.error(f"Error Code: {response.status}")
    return None

async def get_naver_rank_async(NAVER_CLIENT_ID, NAVER_CLIENT_SECRET, keyword, target_url):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET를 설정해주세요.")

    SEARCH_URL = 'https://openapi.naver.com/v1/search/shop.json'
    headers = {
        'X-Naver-Client-Id': NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    }

    product_id = extract_product_id(target_url)
    if product_id:
        target_url = convert_to_naver_url(product_id)

    semaphore = asyncio.Semaphore(10)

    # async with aiohttp.ClientSession() as session:
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        tasks = []
        for start in range(1, 1001, 100):
            params = {
                'query': keyword,
                'display': 100,
                'start': start,
                'sort': 'sim',
            }
            logger.debug(f"[{keyword}] queueing fetch start={start}, target_url={target_url}")
            task = asyncio.create_task(
                fetch(session, SEARCH_URL, headers, params, start, target_url, semaphore)
            )
            tasks.append(task)
            await asyncio.sleep(0.1)

        # 실제 API 호출 & 응답 수집
        responses = await asyncio.gather(*tasks)

        # 받은 응답을 하나씩 찍어봅니다.
        for idx, result in enumerate(responses):
            logger.debug(f"[{keyword}] response #{idx} → {result!r}")
            if result is not None:
                # result가 (rank, image_url) 같은 튜플이라면
                # rank, image_url = result
                logger.info(f"[{keyword}] 최종 매칭 → {result!r}")
                return result

    return -1


def get_naver_rank(keyword, target_url):
    # NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 확인
    if not naver_client_id or not naver_client_secret:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET를 마이페이지에서 설정해주세요.")

    # 비동기 함수 호출
    return async_to_sync(get_naver_rank_async)(naver_client_id, naver_client_secret, keyword, target_url)

import datetime
import urllib.request
import json
from proxy_config import proxies

import datetime
import urllib.request
import json
import logging
from decouple import config
from proxy_config import proxies
from urllib.error import HTTPError, URLError
import ssl

dev_naver_client_id = config('DEV_NAVER_CLIENT_ID', default=None)
dev_naver_client_secret = config('DEV_NAVER_CLIENT_SECRET', default=None)

def get_data_lab_trend(keywords, start_date, end_date, time_unit='date', device='pc'):
    """
    DataLab API를 호출하여,
    주어진 기간(start_date ~ end_date)과 키워드 목록(keywords)에 대한 검색어 트렌드 데이터를 JSON 형태로 반환합니다.
    
    time_unit: 일별 데이터를 조회하려면 "date" (또는 주/월 단위로 "week", "month" 사용)
    """
 
    
    if not dev_naver_client_id or not dev_naver_client_secret:
        raise ValueError("DEV_NAVER_CLIENT_ID와 DEV_NAVER_CLIENT_SECRET가 설정되지 않았습니다.")
    
    url = "https://openapi.naver.com/v1/datalab/search"

    # keywordGroups 생성
    keyword_groups = []
    for kw in keywords:
        keyword_groups.append({
            "groupName": kw,
            "keywords": [kw]
        })

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        "keywordGroups": keyword_groups,
        "device": device
    }
    
    request_body = json.dumps(body, ensure_ascii=False).encode('utf-8')
    
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", dev_naver_client_id)
    req.add_header("X-Naver-Client-Secret", dev_naver_client_secret)
    req.add_header("Content-Type", "application/json")
    

    try:
        ssl_context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, data=request_body, context=ssl_context) as response:
            rescode = response.getcode()
            response_body = response.read().decode('utf-8')
            if rescode == 200:
                data = json.loads(response_body)
                return data
            else:
                return None
    except HTTPError as e:
        try:
            error_body = e.read().decode('utf-8')
        except Exception:
            error_body = "응답 본문 읽기 실패"
        logger.error("DataLab API HTTPError: %s, 응답: %s", e, error_body)
        return None
    except URLError as e:
        logger.error("DataLab API URLError: %s", e)
        return None
    except Exception as e:
        logger.error("DataLab API 호출 중 오류: %s", e)
        return None







import requests
import time
import hmac
import hashlib
import base64
import pandas as pd

# 환경 변수 값
CUSTOMER_ID = config('NAVER_AD_CUSTOMER_ID', default=None)
NAVER_AD_ACCESS = config('NAVER_AD_ACCESS', default=None)
NAVER_AD_SECRET = config('NAVER_AD_SECRET', default=None)
BASE_URL = "https://api.searchad.naver.com"

def naver_generate_signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    """
    timestamp: 밀리초 단위 현재시간 (문자열)
    method: "GET" 또는 "POST"
    uri: 쿼리 파라미터 제외한 API 경로 (예: "/keywordstool")
    secret_key: 광고 API 비밀키 (NAVER_AD_SECRET)
    
    위 값들을 이용해 HMAC-SHA256 해시를 생성하고, base64로 인코딩한 서명을 반환합니다.
    """
    message = f"{timestamp}.{method}.{uri}"
    sign = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(sign).decode('utf-8')

def _get_header(method: str, uri: str, api_key: str, secret_key: str, customer_id: str):
    """
    네이버 광고 API 호출 시 필요한 헤더를 생성합니다.
    - X-API-KEY: 발급받은 광고 API 키 (NAVER_AD_ACCESS)
    - X-Customer: 광고주 ID (NAVER_AD_CUSTOMER_ID)
    - X-Signature: 비밀키(NAVER_AD_SECRET)를 사용해 생성한 서명
    """
    timestamp = str(int(time.time() * 1000))
    signature = naver_generate_signature(timestamp, method, uri, secret_key)
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": signature,
    }

def get_rel_keywords(keywords):
    """
    네이버 광고 API의 /keywordstool 엔드포인트를 통해
    주어진 키워드들의 월간 검색수(PC+모바일), 경쟁 정도 등의 정보를 조회합니다.
    
    keywords: ['방석', '쿠션'] 등 리스트
    
    반환:
        pandas DataFrame 형식으로 keywordList가 반환됩니다.
    """
    uri = '/keywordstool'
    method = 'GET'
    
    # hintKeywords를 쉼표로 구분된 문자열로 전달 (최대 5개)
    hint_param = ','.join(keywords)
    
    params = {
        'hintKeywords': hint_param,
        'showDetail': '1'
    }
    
    headers = _get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = requests.get(BASE_URL + uri, params=params, headers=headers, timeout=30)
            if r.status_code == 200:
                data = r.json()
                df = pd.DataFrame(data['keywordList'])
                # monthlyPcQcCnt 컬럼을 숫자형으로 변환 ("< 10"인 경우는 0으로 처리)
                if 'monthlyPcQcCnt' in df.columns:
                    df['monthlyPcQcCnt'] = pd.to_numeric(df['monthlyPcQcCnt'], errors='coerce').fillna(0).astype(int)
                # monthlyMobileQcCnt 컬럼도 숫자형으로 변환
                if 'monthlyMobileQcCnt' in df.columns:
                    df['monthlyMobileQcCnt'] = pd.to_numeric(df['monthlyMobileQcCnt'], errors='coerce').fillna(0).astype(int)
                # PC와 모바일 검색수를 합산한 새로운 컬럼 생성
                df['totalSearchCount'] = df['monthlyPcQcCnt'] + df['monthlyMobileQcCnt']
                
                # 전달받은 키워드와 동일한 relKeyword만 필터링 (예: '방석')
                searched_keyword = keywords[0]
                df = df[df['relKeyword'] == searched_keyword]
                
                for index, row in df.iterrows():
                    logger.debug("Keyword: %s, monthlyPcQcCnt: %s, monthlyMobileQcCnt: %s, totalSearchCount: %s", 
                                 row.get('relKeyword'), row.get('monthlyPcQcCnt'), row.get('monthlyMobileQcCnt'), row.get('totalSearchCount'))
                return df
            
            # -- 429 Too Many Requests --
            elif r.status_code == 429:
                logger.warning("429 Too Many Requests (Rate Limit). 재시도 대기...")
                time.sleep(3)
                continue
            
            else:
                logger.error("광고 API Error: %s, 응답: %s", r.status_code, r.text)
                return None
        
        except Exception as e:
            logger.error("광고 API 호출 중 오류: %s", e)
            return None

    return None




def get_estimated_search_volume(keywords, start_date, end_date):
    """
    네이버 광고 API(get_rel_keywords)와 DataLab API(get_data_lab_trend)를 사용해,
    주어진 기간(start_date ~ end_date) 동안,  
    각 날짜별로 키워드의 estimatedVolume을 계산하여 반환합니다.
    
    계산식:
        estimatedVolume = ratio * (totalSearchCount / 100)
    
    반환 예시:
        {
            '방석': [
                { 'period': '2023-01-01', 'ratio': 40.5, 'estimatedVolume': 16200 },
                { 'period': '2023-01-02', 'ratio': 38.0, 'estimatedVolume': 15200 },
                ...
            ]
        }
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 1) DataLab API 호출: 일별 데이터를 받기 위해 time_unit='date'
    datalab_data = get_data_lab_trend(
        keywords=keywords,
        start_date=start_date,
        end_date=end_date,
        time_unit='date',
        device='pc'
    )
    if not datalab_data or 'results' not in datalab_data:
        logger.error("DataLab API 결과가 없거나 잘못되었습니다.")
        return None
    
    # 2) 광고 API 호출: 월간 총 검색수 (PC+모바일 합산)을 사용
    ad_df = get_rel_keywords(keywords)
    if ad_df is None or ad_df.empty:
        logger.error("광고 API 결과가 없거나 잘못되었습니다.")
        return None

    desired_keyword = keywords[0]
    filtered_df = ad_df[ad_df['relKeyword'] == desired_keyword]
    if filtered_df.empty:
        logger.error("광고 API 결과에서 해당 키워드 (%s)가 존재하지 않습니다.", desired_keyword)
        return None

    total_search = int(filtered_df.iloc[0]['totalSearchCount'])
    logger.debug("Desired keyword: %s, total monthly search count: %s", desired_keyword, total_search)
    
    # 3) 일별 추정 검색량 계산
    daily_results = []
    results_list = datalab_data["results"]
    
    for record in results_list:
        for row in record.get("data", []):
            period = row.get("period")
            try:
                ratio = float(row.get("ratio", 0))
            except (ValueError, TypeError):
                ratio = 0.0
            estimated = int(ratio * (total_search / 100.0))
            daily_results.append({
                "period": period,
                "ratio": ratio,
                "estimatedVolume": estimated
            })
            logger.debug("Daily record for %s: ratio=%s, estimatedVolume=%s", period, ratio, estimated)
    
    return { desired_keyword: daily_results }


