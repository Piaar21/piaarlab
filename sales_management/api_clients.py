import requests
import time
import hmac
import hashlib
from decouple import config
import logging
import urllib.parse
import json
from datetime import datetime, timedelta
import pytz



logger = logging.getLogger(__name__)

ST_API_KEY = config('ST_API_KEY', default=None)
ST_SECRET_KEY = config('ST_SECRET_KEY', default=None)

COUPANG_ACCOUNTS = [
    {
        'names': ['A00291106','쿠팡01'],
        'access_key': config('COUPANG_ACCESS_KEY_01', default=None),
        'secret_key': config('COUPANG_SECRET_KEY_01', default=None),
        'vendor_id': config('COUPANG_VENDOR_ID_01', default=None),
    },
    {
        'names': ['A00800631','쿠팡02'],
        'access_key': config('COUPANG_ACCESS_KEY_02', default=None),
        'secret_key': config('COUPANG_SECRET_KEY_02', default=None),
        'vendor_id': config('COUPANG_VENDOR_ID_02', default=None),
    },
    # 필요에 따라 추가
]

def generate_coupang_signature(method, url_path, query_params, secret_key):
    datetime_now = time.strftime('%y%m%dT%H%M%SZ', time.gmtime())

    # 1) Canonical Query String
    sorted_query_params = sorted(query_params.items())
    canonical_query_string = '&'.join(
        [f"{key}={urllib.parse.quote(str(value), safe='~')}" for key, value in sorted_query_params]
    )

    # 2) 메시지 구성
    message = datetime_now + method + url_path + canonical_query_string

    # 3) HMAC 서명
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature, datetime_now

#상품리포트 시작
def fetch_coupang_all_seller_products(account_info, max_per_page=100):
    """
    쿠팡 등록상품 목록 '페이징' 조회 후 모든 상품을 합쳐 반환.
    (쿠팡 정책상 max_per_page는 1~100 범위)
    """
    logger.info(f"[fetch_coupang_all_seller_products] START: vendor_id={account_info.get('vendor_id')}, max_per_page={max_per_page}")

    method = 'GET'
    url_path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    vendor_id = account_info.get('vendor_id')
    if not vendor_id:
        msg = f"{account_info['names'][0]}: vendor_id가 없습니다."
        logger.error(msg)
        return False, msg

    next_token = ''
    all_products = []
    max_retries = 3

    page_count = 0

    while True:
        query_params = {
            "vendorId": vendor_id,
            "maxPerPage": max_per_page,
        }
        if next_token:
            query_params["nextToken"] = next_token

        signature, datetime_now = generate_coupang_signature(
            method, url_path, query_params, account_info["secret_key"]
        )
        authorization = (
            f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
            f"signed-date={datetime_now}, signature={signature}"
        )
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": authorization,
        }

        sorted_params = sorted(query_params.items())
        encoded_query = urllib.parse.urlencode(sorted_params, safe='~')
        endpoint = f"https://api-gateway.coupang.com{url_path}?{encoded_query}"

        logger.debug(f"[fetch_coupang_all_seller_products] Requesting endpoint={endpoint}")

        retry_count = 0
        while True:
            try:
                resp = requests.get(endpoint, headers=headers, timeout=30)
            except requests.exceptions.Timeout:
                if retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"[fetch_coupang_all_seller_products] Timeout → 재시도 {retry_count}/{max_retries}")
                    time.sleep(0.2)
                    continue
                else:
                    msg = f"[fetch_coupang_all_seller_products] Timeout {max_retries}회 초과"
                    logger.error(msg)
                    return False, msg
            except requests.exceptions.RequestException as e:
                msg = f"[fetch_coupang_all_seller_products] RequestException: {str(e)}"
                logger.error(msg)
                return False, msg

            if resp.status_code == 200:
                # 정상 응답
                data_json = resp.json()
                code = data_json.get("code")

                if code != "SUCCESS":
                    msg = f"[fetch_coupang_all_seller_products] code != SUCCESS, raw={data_json}"
                    logger.error(msg)
                    return False, msg

                data_list = data_json.get("data", [])
                all_products.extend(data_list)

                next_token = data_json.get("nextToken", "")
                page_count += 1

                logger.info(
                    f"[fetch_coupang_all_seller_products] Page {page_count} fetched: "
                    f"{len(data_list)} items, nextToken={next_token}"
                )

                # 필요 시 JSON 전체를 로깅하고 싶으면 (주의: 매우 길어질 수 있음)
                logger.debug(f"Page JSON:\n{json.dumps(data_json, indent=2, ensure_ascii=False)}")

                break  # while True for retry -> break
            else:
                # 비정상 응답
                try:
                    err_json = resp.json()
                except:
                    err_json = {}
                msg = f"[fetch_coupang_all_seller_products] HTTP {resp.status_code}, text={resp.text}"
                logger.error(msg)
                return False, msg

        if not next_token:
            # 더 이상 페이지 없음
            logger.info(f"[fetch_coupang_all_seller_products] nextToken이 없으므로 종료")
            break

        # Rate limit 고려
        time.sleep(0.2)

    logger.info(f"[fetch_coupang_all_seller_products] All pages fetched. total items={len(all_products)}")

    # 필요 시 전부 반환 대신 일부만 slice
    recent_10 = all_products[:150]
    return True, recent_10


def get_coupang_seller_product(account_info, seller_product_id):
    """
    등록상품ID(seller_product_id)로 쿠팡 상품 정보를 조회.
    → items 배열에 vendorItemId 등 옵션 목록이 포함됨.
    """
    access_key = account_info.get('access_key')
    secret_key = account_info.get('secret_key')
    if not (access_key and secret_key):
        msg = f"{account_info['names'][0]}: Coupang API 계정(access_key/secret_key) 누락!"
        logger.error(msg)
        return False, msg

    method = "GET"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
    query_params = {}

    signature, datetime_now = generate_coupang_signature(
        method, url_path, query_params, secret_key
    )

    host = "https://api-gateway.coupang.com"
    canonical_query = '&'.join([
        f"{k}={urllib.parse.quote(str(v), safe='~')}" for k,v in query_params.items()
    ])
    endpoint = f"{host}{url_path}"
    if canonical_query:
        endpoint += f"?{canonical_query}"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        ),
    }

    # 기존의 endpoint 로그는 주석 처리
    # logger.debug(f"[get_coupang_seller_product] GET {endpoint}")

    try:
        resp = requests.get(endpoint, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()

            # # ★★ 여기서 “API로 받아온 JSON”만 이쁘게 로그로 출력 ★★
            # logger.debug(
            #     "[get_coupang_seller_product] Response JSON:\n%s",
            #     json.dumps(data, ensure_ascii=False, indent=2)
            # )

            code = data.get("code")
            if code != "SUCCESS":
                msg = f"[get_coupang_seller_product] code != SUCCESS, raw={data}"
                logger.error(msg)
                return False, msg

            product_info = data.get("data", {})
            # logger.info(f"[get_coupang_seller_product] seller_product_id={seller_product_id} 조회완료.")
            # logger.debug(f"[get_coupang_seller_product] product_info keys={list(product_info.keys())}")
            # items = product_info.get("items", [])
            # logger.debug(f"[get_coupang_seller_product] items.len={len(items)}")

            return True, product_info

        elif resp.status_code == 404:
            msg = f"[get_coupang_seller_product] 404 Not Found: seller_product_id={seller_product_id}"
            logger.warning(msg)
            return False, msg

        else:
            msg = f"[get_coupang_seller_product] status={resp.status_code}, text={resp.text}"
            logger.error(msg)
            return False, msg

    except requests.exceptions.RequestException as e:
        msg = f"[get_coupang_seller_product] 요청 예외: {str(e)}"
        logger.error(msg)
        return False, msg
    

    #매출리포트 시작

def fetch_coupang_ordersheets(
    start_date=None,
    end_date=None,
    status="INSTRUCT",
    max_per_page=50,
    next_token=None
):
    """
    쿠팡 '발주서 목록 조회(일단위 페이징)' API를 여러 계정에 대해 호출하여 결과를 합침.

    - GET /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets
    - 파라미터:
        start_date: createdAtFrom (YYYY-MM-DD)
        end_date:   createdAtTo   (YYYY-MM-DD)
        status:     주문 상태(INSTRUCT, WAITING 등)
        max_per_page: 페이지 당 건수
        next_token: 다음 페이지 토큰(처음엔 None)
    - 반환: (True, merged_data) / (False, "에러메시지")
      merged_data = {
          "contents": [...],        # 모든 계정의 ordersheet를 합친 리스트
          "partial_errors": [...]   # 일부 계정 실패 시 에러 메세지
      }
    """

    # (A) 날짜 기본값 처리
    #     만약 start_date, end_date 둘 중 하나라도 없으면 오늘 날짜, 어제 날짜 등 자동할당
    if not start_date or not end_date:
        kst = pytz.timezone("Asia/Seoul")
        now_kst = datetime.now(kst)

        if not end_date:
            end_date = now_kst.strftime('%Y-%m-%d')

        if not start_date:
            # 기본적으로 end_date 기준 -1일 (1일 범위 예시)
            # 필요 시 -7일 등 원하는 범위로 조정 가능
            start_dt = now_kst - timedelta(days=1)
            start_date = start_dt.strftime('%Y-%m-%d')

    # (B) 결과를 쌓을 리스트
    all_contents = []
    partial_fails = []

    # (C) 모든 쿠팡 계정 반복
    for acc_info in COUPANG_ACCOUNTS:
        acc_name = acc_info.get('names', ["COUPANG"])[0]
        vendor_id = acc_info.get('vendor_id')
        access_key = acc_info.get('access_key')
        secret_key = acc_info.get('secret_key')

        if not (vendor_id and access_key and secret_key):
            msg = f"[{acc_name}] 쿠팡 계정정보(vendor_id/access_key/secret_key) 누락!"
            partial_fails.append(msg)
            continue

        # (D) 요청 준비
        method = "GET"
        url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/ordersheets"

        # Query Params
        query_params = {
            "createdAtFrom": start_date,  # YYYY-MM-DD
            "createdAtTo": end_date,      # YYYY-MM-DD
            "maxPerPage": max_per_page,
            "status": status,            # 기본 "INSTRUCT"
        }
        if next_token:
            query_params["nextToken"] = next_token

        # 시그니처 생성 준비
        sorted_query_params = sorted(query_params.items())
        canonical_query_string = '&'.join(
            f"{k}={urllib.parse.quote(str(v), safe='~')}"
            for k, v in sorted_query_params
        )

        # 시그니처 생성
        signature, datetime_now = generate_coupang_signature(
            method, url_path, dict(sorted_query_params), secret_key
        )

        host = "https://api-gateway.coupang.com"
        endpoint = f"{host}{url_path}"
        if canonical_query_string:
            endpoint += f"?{canonical_query_string}"

        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": (
                f"CEA algorithm=HmacSHA256, access-key={access_key}, "
                f"signed-date={datetime_now}, signature={signature}"
            ),
        }

        logger.debug(f"[fetch_coupang_ordersheets] {acc_name} => {endpoint}")

        # (E) 최대 재시도 횟수
        MAX_RETRIES = 3
        retry_count = 0
        success_for_acc = False

        while retry_count < MAX_RETRIES:
            try:
                resp = requests.get(endpoint, headers=headers, timeout=30)
                logger.debug(f"[fetch_coupang_ordersheets] {acc_name} status={resp.status_code}")
                logger.debug("[fetch_coupang_ordersheets] response => %s", resp.text)

                if resp.status_code == 200:
                    data = resp.json()
                    code = data.get("code")
                    if code == "SUCCESS":
                        # data["data"]["orderSheetList"] 형태로 주문서 목록 있을 가능성
                        # 실제 응답 구조 확인 필요
                        data_obj = data.get("data", {})
                        orders = data_obj.get("orderSheetList", [])

                        logger.info(f"[{acc_name}] 쿠팡 발주서 {len(orders)}개 nextToken={data_obj.get('nextToken')}")
                        # 계정명(acc_name) 태그
                        for od in orders:
                            od['accountName'] = acc_name
                        all_contents.extend(orders)
                        success_for_acc = True
                        break
                    else:
                        msg = f"[{acc_name}] code != SUCCESS, raw={data}"
                        logger.error(msg)
                        partial_fails.append(msg)
                        break

                elif resp.status_code == 429:
                    # Rate Limit
                    retry_count += 1
                    logger.warning(f"[{acc_name}] RateLimit(429) → 재시도 {retry_count}/{MAX_RETRIES}")
                    time.sleep(3)
                    continue

                else:
                    msg = f"[{acc_name}] status={resp.status_code}, resp={resp.text}"
                    logger.error(msg)
                    partial_fails.append(msg)
                    break

            except requests.exceptions.RequestException as e:
                msg = f"[{acc_name}] 요청 예외: {str(e)}"
                logger.error(msg)
                partial_fails.append(msg)
                break

        if not success_for_acc:
            logger.warning(f"[{acc_name}] 최종 실패 => partial_fails에 기록")

    # (F) 모든 계정 반복 끝
    if not all_contents and partial_fails:
        # 전부 실패
        return (False, f"모든 쿠팡 계정 실패 => {partial_fails}")

    # (G) 부분 성공 or 전체 성공
    merged_data = {"contents": all_contents}
    if partial_fails:
        merged_data["partial_errors"] = partial_fails
        logger.warning(f"[fetch_coupang_ordersheets] 부분실패 => total={len(all_contents)}")
        return (True, merged_data)
    else:
        logger.info(f"[fetch_coupang_ordersheets] 전부 성공 => total={len(all_contents)}")
        return (True, merged_data)
    


def generate_signature(api_key, secret_key, timestamp):
    data = (api_key + timestamp).encode('utf-8')
    secret_key_bytes = secret_key.encode('utf-8')
    signature = hmac.new(secret_key_bytes, data, hashlib.sha256).hexdigest()
    return signature

def get_headers():
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(ST_API_KEY, ST_SECRET_KEY, timestamp)
    return {
        'x-sellertool-apiKey': ST_API_KEY,
        'x-sellertool-timestamp': timestamp,
        'x-sellertool-signiture': signature,
        'Content-Type': 'application/json'
    }    

REQUEST_URL = "https://sellertool-api-server-function.azurewebsites.net/api/product-options/search/by-optionCodes"


def fetch_seller_tool_option_info(option_codes):
    """
    option_codes: list of string, e.g. ["NH21A05-CB", "AB1234-OPT"]
    Returns: dict (API 응답 JSON)
    """
    # POST 요청 바디
    payload = {
        "optionCodes": option_codes
    }
    # 헤더 생성
    headers = get_headers()

    # API 요청
    response = requests.post(REQUEST_URL, json=payload, headers=headers)
    response.raise_for_status()  # HTTP 에러 시 예외 발생

    # 응답 JSON
    data = response.json()
    return data