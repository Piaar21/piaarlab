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
import os


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

REQUEST_URL = "https://shared-api.sellertool.io/api/product-options/search/by-optionCodes"


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




#네이버시작
import requests
import time
import hmac
import hashlib
from decouple import config
import logging
import urllib.parse
import json
from datetime import datetime, timedelta,timezone
import pytz
import bcrypt
import base64
from proxy_config import proxies
from collections import defaultdict

# 네이버 계정 정보 불러오기
NAVER_ACCOUNTS = [
    {
        'names': ['니뜰리히'],  # 예: 동일 계정에 여러 변형된 이름
        'client_id': config('NAVER_CLIENT_ID_01', default=None),
        'client_secret': config('NAVER_CLIENT_SECRET_01', default=None),
    },
    {
        'names': ['수비다', '수비다 SUBIDA'],  # 예: 여러 스토어명 변형
        'client_id': config('NAVER_CLIENT_ID_02', default=None),
        'client_secret': config('NAVER_CLIENT_SECRET_02', default=None),
    },
    {
        'names': ['노는개최고양', '노는 개 최고양'],  # 예: 스페이스나 변형된 이름
        'client_id': config('NAVER_CLIENT_ID_03', default=None),
        'client_secret': config('NAVER_CLIENT_SECRET_03', default=None),
    },
    {
        'names': ['아르빙'],  # 예: 공백 추가 변형
        'client_id': config('NAVER_CLIENT_ID_04', default=None),
        'client_secret': config('NAVER_CLIENT_SECRET_04', default=None),
    },
    # 필요에 따라 추가
]

naver_ad_access = config('NAVER_AD_ACCESS', default=None)
naver_ad_secret = config('NAVER_AD_SECRET', default=None)


# 네이버 API 액세스 토큰 가져오기
def fetch_naver_access_token(account_info):
    # 타임스탬프 생성 (밀리초 단위)
    timestamp = str(int(time.time() * 1000) - 3000)
    pwd = f"{account_info['client_id']}_{timestamp}".encode('utf-8')

    # bcrypt를 사용하여 client_secret_sign 생성
    bcrypt_salt = account_info['client_secret'].encode('utf-8')
    hashed_pwd = bcrypt.hashpw(pwd, bcrypt_salt)
    client_secret_sign = base64.urlsafe_b64encode(hashed_pwd).decode('utf-8')

    url = 'https://api.commerce.naver.com/external/v1/oauth2/token'
    params = {
        'client_id': account_info['client_id'],
        'timestamp': timestamp,
        'client_secret_sign': client_secret_sign,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    response = requests.post(url, data=params,proxies=proxies)
    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 0)
        account_info['access_token'] = access_token
        account_info['token_expires_at'] = datetime.now() + timedelta(seconds=expires_in)
        return access_token
    else:
        logger.error(f"{account_info['names'][0]} 액세스 토큰 발급 실패: {response.text}")
        return None


    
def get_access_token(account_info):
    print("account_info in fetch_naver_access_token:", account_info)
    access_token = account_info.get('access_token')
    expires_at = account_info.get('token_expires_at')

    if access_token and expires_at and expires_at > datetime.now():
        return access_token
    else:
        return fetch_naver_access_token(account_info)



def fetch_naver_products(account_info, max_count=250):
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        logger.error(f"{account_info['names'][0]}: 액세스 토큰 발급 실패!")
        return False, "토큰 발급 실패"

    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    PAGE_SIZE = 50
    MAX_RETRIES = 3

    all_products = []
    current_page = 1

    while True:
        payload = {
            "searchKeywordType": "SELLER_CODE",
            "productStatusTypes": ["SALE","OUTOFSTOCK"],
            "page": current_page,
            "size": PAGE_SIZE,
            "orderType": "NO",
        }

        logger.debug(f"[fetch_naver_products] Request(page={current_page}) => {url}, payload={payload}")

        retry_count = 0
        while retry_count < MAX_RETRIES:
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30, proxies=proxies)
                logger.debug(f"[fetch_naver_products] status_code={resp.status_code}")
                logger.debug(f"[fetch_naver_products] response snippet => {resp.text[:300]}")

                if resp.status_code == 429:
                    logger.warning("Rate Limit 발생! 10초 후 재시도...")
                    time.sleep(10)
                    retry_count += 1
                    continue

                elif resp.status_code == 200:
                    data = resp.json()

                    # logger.debug(f"[fetch_naver_products] 응답 데이터 전체: {json.dumps(data, ensure_ascii=False, indent=2)}")


                    products = data.get("contents", [])
                    total_el = data.get("totalElements", 0)

                    all_products.extend(products)

                    # 만약 누적된 상품이 max_count(5개) 이상이면 그만 가져옴
                    if len(all_products) >= max_count:
                        # 필요한 만큼만 잘라서 반환
                        return True, all_products[:max_count]

                    # 다음 페이지 갈지 말지 결정
                    if len(products) < PAGE_SIZE or len(all_products) >= total_el:
                        # 더 이상 페이지가 없으면 반환 (5개 미만일 수도 있지만)
                        return True, all_products

                    current_page += 1
                    break

                else:
                    detail_msg = f"{resp.status_code}, {resp.text}"
                    logger.error(f"{account_info['names'][0]} 상품목록 조회 실패: {detail_msg}")
                    return False, detail_msg

            except requests.exceptions.RequestException as e:
                msg = f"{account_info['names'][0]} 상품목록 조회 중 예외 발생: {str(e)}"
                logger.error(msg)
                return False, msg

        if retry_count >= MAX_RETRIES:
            msg = f"{account_info['names'][0]} 429 재시도 {MAX_RETRIES}회 초과, 목록 조회 중단"
            logger.error(msg)
            return False, msg

def get_naver_minimal_product_info(account_info, origin_product_no):
    """
    네이버 원상품(originProduct) 상세 정보를 조회하고,
    대표이미지/판매가/재고수량/옵션정보 등을 추출해 dict로 반환.
    """
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        msg = f"{account_info['names'][0]}: 액세스 토큰 발급 실패!"
        return False, msg

    url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{origin_product_no}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    MAX_RETRIES = 3
    retry_count = 0

    while retry_count < MAX_RETRIES:
        try:
            resp = requests.get(url, headers=headers, timeout=30, proxies=proxies)

            if resp.status_code == 429:
                time.sleep(10)
                retry_count += 1
                continue

            elif resp.status_code == 200:
                data = resp.json()
                # logger.debug(
                #     "[DETAIL] originNo=%s response data:\n%s",
                #     origin_product_no,
                #     json.dumps(data, ensure_ascii=False, indent=2)
                # )

                origin_prod = data.get("originProduct", {})
                sale_price  = origin_prod.get("salePrice")
                stock_qty   = origin_prod.get("stockQuantity")

                images_part = origin_prod.get("images", {})
                rep_img_dict = images_part.get("representativeImage", {})

                detail_attr = origin_prod.get("detailAttribute", {})
                option_info   = detail_attr.get("optionInfo", {})
                option_combos = option_info.get("optionCombinations", [])

                # 옵션 파싱
                option_rows = []
                for combo in option_combos:
                    row = {
                        "id": combo.get("id"),
                        "optionName1": combo.get("optionName1"),
                        "optionName2": combo.get("optionName2"),
                        "stockQuantity": combo.get("stockQuantity"),
                        "price": combo.get("price"),
                        "sellerManagerCode": combo.get("sellerManagerCode"),
                    }
                    option_rows.append(row)

                seller_code_dict = detail_attr.get("sellerCodeInfo", {})
                seller_mgmt_code = seller_code_dict.get("sellerManagerCode", "")

                result = {
                    "representativeImage": rep_img_dict,
                    "salePrice": sale_price,
                    "stockQuantity": stock_qty,
                    "optionCombinations": option_rows,
                    "sellerCodeInfo": {
                        "sellerManagerCode": seller_mgmt_code
                    }
                }

                return True, result

            else:
                msg = (
                    f"[get_naver_minimal_product_info] 원상품 조회 실패 "
                    f"originNo={origin_product_no}: {resp.status_code}, {resp.text}"
                )
                return False, msg

        except requests.exceptions.RequestException as e:
            msg = f"[get_naver_minimal_product_info] 요청 중 예외 발생 originNo={origin_product_no}: {str(e)}"
            return False, msg

    msg = f"[get_naver_minimal_product_info] 429 재시도 {MAX_RETRIES}회 초과, originNo={origin_product_no} 요청 중단"
    return False, msg



def fetch_naver_products_with_details(account_info):
    """
    1) fetch_naver_products (상품목록) 호출
    2) 각 상품별 get_naver_minimal_product_info (원상품 상세조회)
    3) 옵션정보까지 병합한 detailed_list 를 반환
    """
    logger.info("===== [fetch_naver_products_with_details] START =====")
    import time

    # (A) 상품 목록 조회
    is_ok, base_list = fetch_naver_products(account_info)
    if not is_ok:
        return False, base_list  # base_list가 에러 메시지

    detailed_list = []
    for i, item in enumerate(base_list, start=1):
        origin_no = item.get("originProductNo")
        ch_products = item.get("channelProducts", [])

        # 상품명 추출
        product_name = "(상품명없음)"
        if ch_products:
            product_name = ch_products[0].get("name", product_name)

        # (B) 채널에서 할인 가격(있다면) 추출
        discounted_price_api = 0
        if ch_products:
            discounted_price_api = ch_products[0].get("discountedPrice", 0)
            # 모바일 할인가 등을 우선적으로 쓰고 싶다면 이 부분 수정 가능

        if not origin_no:
            # originProductNo가 없으면 건너뜀
            continue

        # (C) 원상품 상세 조회
        is_ok2, detail_info = get_naver_minimal_product_info(account_info, origin_no)
        if not is_ok2:
            return False, detail_info  # detail_info가 에러 메시지

        # (D) 상세정보 + 목록 정보 병합
        merged = {
            "originProductNo": origin_no,
            "channelProductNo": ch_products[0].get("channelProductNo", "") if ch_products else "",
            "productName": product_name,
            "representativeImage": detail_info.get("representativeImage"),
            "salePrice": detail_info.get("salePrice"),
            "discountedPrice": discounted_price_api,
            "stockQuantity": detail_info.get("stockQuantity"),
            "sellerCodeInfo": detail_info.get("sellerCodeInfo"),
            "optionCombinations": detail_info.get("optionCombinations", []),
        }
        detailed_list.append(merged)

        # API 호출 과도 시 429 방지용 sleep
        time.sleep(1)

    logger.info("[fetch_naver_products_with_details] 최종 detailed_list 개수=%d", len(detailed_list))
    return True, detailed_list

#매출리포트 시작

def fetch_naver_sales(account_info, start_date, end_date):
    logger.info("===== [fetch_naver_sales] START =====")

    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        return {
            "code": 401,
            "message": "No AccessToken",
            "data": []
        }

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    kst = timezone(timedelta(hours=9))
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=kst)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=kst)

    delta = timedelta(hours=24)
    current_date = start_date

    # ★ 중복 제거 set
    all_product_order_ids = set()
    max_retries = 3

    while current_date <= end_date:
        last_changed_from = current_date.isoformat(timespec='milliseconds')
        last_changed_to   = (current_date + delta).isoformat(timespec='milliseconds')

        params = {
            'lastChangedFrom': last_changed_from,
            'lastChangedTo':   last_changed_to,
            'limitCount': 300,
        }

        more_sequence = None

        while True:
            if more_sequence:
                params['moreSequence'] = more_sequence

            retry_count = 0
            while True:
                try:
                    response = requests.get(
                        'https://api.commerce.naver.com/external/v1/pay-order/seller/product-orders/last-changed-statuses',
                        headers=headers,
                        params=params,
                        timeout=30,
                        proxies=proxies,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        last_change_statuses = data.get('data', {}).get('lastChangeStatuses', [])

                        for order in last_change_statuses:
                            product_order_id = order.get('productOrderId')
                            if product_order_id:
                                all_product_order_ids.add(product_order_id)

                        more = data.get('data', {}).get('more', {})
                        if more:
                            more_sequence = more.get('moreSequence')
                            params['lastChangedFrom'] = more.get('moreFrom')
                            time.sleep(1)
                        else:
                            break
                        retry_count = 0

                    elif response.status_code == 429:
                        if retry_count < max_retries:
                            retry_count += 1
                            logger.error("Rate limit. retry %d/%d", retry_count, max_retries)
                            time.sleep(5)
                            continue
                        else:
                            logger.error("Rate limit repeated. stop this range.")
                            break
                    else:
                        logger.error("Order list fail: %d %s", response.status_code, response.text)
                        break
                    break

                except requests.exceptions.Timeout:
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.warning("Timeout. retry %d/%d", retry_count, max_retries)
                        time.sleep(3)
                        continue
                    else:
                        logger.error("Timeout repeated. stop.")
                        break
                except requests.exceptions.RequestException as e:
                    logger.error(f"Request error: {e}")
                    break
            else:
                pass
            break

        current_date += delta

    # (2) orderIds → fetch_naver_order_details
    unique_ids_list = list(all_product_order_ids)
    orders_details = fetch_naver_order_details(account_info, unique_ids_list)

    logger.info("===== [fetch_naver_sales] Logging each order detail =====")
    # logger.info(f"=== Total items in orders_details: {orders_details} ===")

    # ★ 1) 모든 orders_details를 전체 JSON으로 한번에 찍기 (매우 큼 주의)
    # import json
    # full_json_str = json.dumps(orders_details, ensure_ascii=False, indent=2)
    # logger.info(f"[FULL DUMP of orders_details]\n{full_json_str}")

    # OR 2) 아이템별로 나눠서 찍기
    import json
    for idx, item in enumerate(orders_details):
        item_str = json.dumps(item, ensure_ascii=False, indent=2)
        logger.info(f"[FULL ITEM {idx}] =>\n{item_str}")

    logger.info("===== [fetch_naver_sales] Done logging orders_details =====")

    return {
        "code": 200,
        "message": "OK",
        "data": orders_details
    }

def fetch_naver_order_details(account_info, product_order_ids):
    logger.info("===== [fetch_naver_order_details] START =====")
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        return []
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    url = 'https://api.commerce.naver.com/external/v1/pay-order/seller/product-orders/query'
    batch_size = 100
    orders_details = []
    max_retries = 3

    TARGET_ID = "2025021967238061"  # ★ 우리가 로그를 보고 싶은 특정 productOrderId

    for i in range(0, len(product_order_ids), batch_size):
        batch_ids = product_order_ids[i:i+batch_size]
        payload = {
            "productOrderIds": batch_ids,
            "quantityClaimCompatibility": True
        }

        retry_count = 0
        while True:
            try:
                response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30, proxies=proxies)
                if response.status_code == 200:
                    data = response.json()

                    if isinstance(data, list):
                        product_orders = data
                    elif isinstance(data, dict):
                        if 'data' in data and isinstance(data['data'], list):
                            product_orders = data['data']
                        else:
                            product_orders = []
                    else:
                        product_orders = []
                    
                    logger.info(f"추출된 product_orders 수: {len(product_orders)}")

                    # (A) 각 product_orders 아이템을 확인하면서,
                    #     productOrderId == TARGET_ID 면 로그로 전체 item 출력
                    for item in product_orders:
                        product_part = item.get("productOrder", {})
                        order_id = product_part.get("productOrderId")
                        if order_id == TARGET_ID:
                            # 여기서 전체 JSON을 찍음
                            item_str = json.dumps(item, ensure_ascii=False, indent=2)
                            logger.info(
                                f"===== [fetch_naver_order_details] FOUND TARGET ID={TARGET_ID} =====\n{item_str}"
                            )
                    
                    # (B) orders_details 확장
                    orders_details.extend(product_orders)
                    break
                elif response.status_code == 429:
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.error(f"{account_info['names'][0]} 주문 상세 정보 조회 API 호출 제한. 재시도 {retry_count}/{max_retries}")
                        time.sleep(5)
                        continue
                    else:
                        logger.error(f"{account_info['names'][0]} 주문 상세 정보 조회 API 호출 제한 반복 발생. 이 배치 처리 중단.")
                        break
                else:
                    logger.error(f"{account_info['names'][0]} 주문 상세 정보 조회 실패: {response.status_code}, {response.text}")
                    break
            except requests.exceptions.Timeout:
                if retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"{account_info['names'][0]} 주문 상세 정보 조회 타임아웃 발생. 재시도 {retry_count}/{max_retries}")
                    time.sleep(3)
                    continue
                else:
                    logger.error(f"{account_info['names'][0]} 주문 상세 정보 조회 타임아웃 반복 발생. 이 배치 처리 중단.")
                    break
            except requests.exceptions.RequestException as e:
                logger.error(f"요청 중 예외 발생: {e}")
                break

        time.sleep(1)  # Rate Limit 고려

    return orders_details



#광고 시작
CUSTOMER_ID = config('NAVER_AD_CUSTOMER_ID', default=None)
NAVER_AD_ACCESS = config('NAVER_AD_ACCESS', default=None)
NAVER_AD_SECRET = config('NAVER_AD_SECRET', default=None)
BASE_URL = "https://api.searchad.naver.com"
    

def naver_generate_signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    """
    timestamp: 밀리초 단위 현재시간
    method: "GET" / "POST"
    uri: "/stat-reports" 또는 "/stat-reports/{id}", 다운로드 시 "/report-download"
    """
    message = f"{timestamp}.{method}.{uri}"
    sign = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    return base64.b64encode(sign).decode('utf-8')

def get_header(method: str, uri: str, api_key: str, secret_key: str, customer_id: str):
    """
    네이버 검색광고 API 호출 시 필요한 헤더 생성.
    - uri에는 쿼리 파라미터를 제외한 경로만 사용
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


# -------------------
# Master Report
# -------------------
def create_master_report(item: str, from_time: str):
    """
    POST /master-reports
    item 예: "Campaign", "Adgroup", "ShoppingProduct"
    from_time 예: "2025-02-26T00:00:00Z"
    """
    uri = "/master-reports"
    method = "POST"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    body = {
        "item": item,
        "fromTime": from_time
    }
    try:
        response = requests.post(BASE_URL + uri, headers=headers, json=body)
        if response.status_code >= 400:
            logger.error(f"create_master_report Error {response.status_code}, body={response.text}")
        response.raise_for_status()
        data = response.json()
        logger.info(f"[create_master_report] item={item}, response={data}")
        return data
    except requests.RequestException as e:
        logger.error(f"Failed to create master report: {e}")
        return None

def get_master_report(report_id: str):
    """
    GET /master-reports/{report_id}
    """
    uri = f"/master-reports/{report_id}"
    method = "GET"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    try:
        response = requests.get(BASE_URL + uri, headers=headers)
        response.raise_for_status()
        data = response.json()
        logger.info(f"[get_master_report] id={report_id}, response={data}")
        return data
    except requests.RequestException as e:
        logger.error(f"Failed to get master report {report_id}: {e}")
        return None

def delete_all_master_reports():
    """
    MasterReport: delete all
    DELETE /master-reports
    모든 Master Report job을 삭제합니다.
    """
    uri = "/master-reports"
    method = "DELETE"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    try:
        response = requests.delete(BASE_URL + uri, headers=headers)
        response.raise_for_status()
        data = response.json()
        logger.info(f"[delete_all_master_reports] Successfully deleted all master report jobs. Response: {data}")
        return data
    except requests.RequestException as e:
        logger.error(f"[delete_all_master_reports] Failed to delete master report jobs: {e}")
        return None
    
# ----------------------
# 2) Stat Report 생성/조회
# ----------------------
def create_stat_report(report_tp, stat_dt):
    uri = "/stat-reports"
    method = "POST"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    body = {
        "reportTp": report_tp,
        "statDt": stat_dt
    }
    url = BASE_URL + uri
    try:
        resp = requests.post(url, headers=headers, json=body)
        # 아래처럼 상태 코드가 4xx/5xx일 때 응답 바디를 로깅하고 나서 raise_for_status()를 호출
        if resp.status_code >= 400:
            logger.error(f"[create_stat_report] status={resp.status_code}, body={resp.text}")
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"[create_stat_report] reportTp={report_tp}, statDt={stat_dt}, resp={data}")
        return data
    except requests.RequestException as e:
        logger.error(f"[create_stat_report] Failed: {e}")
        return None

def get_stat_report(report_job_id):
    """
    GET /stat-reports/{reportJobId}
    """
    uri = f"/stat-reports/{report_job_id}"
    method = "GET"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    url = BASE_URL + uri
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def download_report(download_url, file_name):
    """
    download_url: 응답에서 받은 downloadUrl
    file_name: 저장할 파일명 (예: "AD_DETAIL_20250226.tsv")
    """
    # 시그니처용 URI는 "/report-download"
    uri = "/report-download"
    method = "GET"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)

    r = requests.get(download_url, headers=headers, stream=True)
    r.raise_for_status()

    # 저장
    if not os.path.exists("download"):
        os.makedirs("download")
    file_path = os.path.join("download", file_name)

    with open(file_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"Downloaded to {file_path}")
    return file_path

def main():
    # 예) 어제 날짜 (YYYYMMDD)로 "AD_DETAIL" 리포트 요청
    yesterday = datetime.now() - timedelta(days=1)
    stat_dt = yesterday.strftime("%Y%m%d")    # 예: "20250226"
    report_tp = "AD_DETAIL"                  # 필요 시 "AD_CONVERSION_DETAIL" 등으로 변경
    
    # 1) 생성
    create_res = create_stat_report(report_tp, stat_dt)
    print("create_stat_report:", create_res)

    if "reportJobId" not in create_res:
        print("reportJobId not found in response. Possibly 400 error or unsupported type.")
        return

    report_job_id = create_res["reportJobId"]
    status = create_res.get("status", "REGIST")
    print(f"reportJobId={report_job_id}, status={status}")

    # 2) 상태 체크 (REGIST, RUNNING, WAITING, etc.)
    while status in ["REGIST", "RUNNING", "WAITING"]:
        print("Waiting for report to be built...")
        time.sleep(5)
        detail_res = get_stat_report(report_job_id)
        status = detail_res.get("status", "ERROR")
        print(f"Check: reportJobId={report_job_id}, status={status}")

    # 3) 상태가 BUILT -> 다운로드. NONE -> 데이터 없음, ERROR -> 빌드실패
    if status == "BUILT":
        download_url = detail_res.get("downloadUrl", "")
        if download_url:
            file_name = f"{report_tp}_{stat_dt}.tsv"
            download_report(download_url, file_name)
        else:
            print("downloadUrl is empty even though status=BUILT.")
    elif status == "NONE":
        print("No data for this report.")
    elif status == "ERROR":
        print("Failed to build stat report.")
    elif status == "AGGREGATING":
        print("Stat aggregation not yet finished.")
    else:
        print(f"Unknown status: {status}")

if __name__ == "__main__":
    main()