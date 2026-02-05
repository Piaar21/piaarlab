import requests
import time
import hmac
import hashlib
import json
from urllib.parse import quote
from decouple import config
import logging
from datetime import datetime, timedelta, timezone  # timezone 추가
import base64
import bcrypt
import urllib.parse
from proxy_config import proxies


logger = logging.getLogger(__name__)


ST_API_KEY = config('ST_API_KEY', default=None)
ST_SECRET_KEY = config('ST_SECRET_KEY', default=None)

REQUEST_URL_INVENTORY = 'https://shared-api.sellertool.io/api/inventories/search/stocks-by-optionCodes'
REQUEST_URL_OPTION_BY_CODE = 'https://shared-api.sellertool.io/api/product-options/search/by-optionCodes'
REQUEST_URL_OPTIONS = 'https://shared-api.sellertool.io/api/product-options'


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


# 쿠팡 계정 정보 불러오기
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

def get_option_info_by_code(option_code):
    url = REQUEST_URL_OPTION_BY_CODE
    headers = get_headers()
    body = {'optionCodes': [option_code]}
    resp = requests.post(url, headers=headers, data=json.dumps(body))
    if resp.status_code == 200:
        result = resp.json()
        if result.get('content'):
            info = result['content'][0]
            product_name = info['product']['name'] if info.get('product') else ''
            sales_price = info.get('salesPrice')
            return {
                'productName': product_name,
                'salesPrice': sales_price
            }
    return None

def get_all_options_by_product_name(product_name):
    headers = get_headers()
    encoded_name = quote(product_name)
    url = REQUEST_URL_OPTIONS + '?productName=' + encoded_name
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        result = resp.json()
        if result.get('content'):
            return [item.get('productOptionCode') or item.get('code') for item in result['content']]
    return []

def get_inventory_by_option_codes(option_codes):
    logger.debug(f"=== DEBUG: [get_inventory] request optionCodes={option_codes}")
    
    url = REQUEST_URL_INVENTORY  # 이미 상단에 정의된 상수
    headers = get_headers()       # 셀러툴 API 인증 헤더
    body = {
        "optionCodes": option_codes
    }

    response = requests.post(url, headers=headers, data=json.dumps(body))
    if response.status_code != 200:
        logger.error(f"=== DEBUG: 재고 API 오류 code={response.status_code}, body={response.text}")
        return {}

    data = response.json()
    # logger.debug(f"=== DEBUG: [get_inventory] response data={data}")

    stock_map = {}
    for item in data.get('content', []):
        code = item['code']
        stock = item['stockUnit']
        stock_map[code] = stock

    return stock_map

def get_options_detail_by_codes(option_codes):
    headers = get_headers()
    body = {'optionCodes': option_codes}
    resp = requests.post(REQUEST_URL_OPTION_BY_CODE, headers=headers, data=json.dumps(body))
    if resp.status_code == 200:
        result = resp.json()
        if result.get('content'):
            detail_map = {}
            for detail in result['content']:
                product_name = detail['product']['name'] if detail.get('product') else ''
                detail_map[detail['code']] = {
                    'salesPrice': detail['salesPrice'],
                    'optionName': detail['name'],
                    'productName': product_name
                }
            return detail_map
    return {}

import logging

logger = logging.getLogger(__name__)

def get_exchangeable_options(input_option_code, needed_qty=1):
    """
    재고 0인 항목은 결과에 포함되지 않도록 수정( stock_unit == 0 → 스킵 ).
    """
    input_info = get_option_info_by_code(input_option_code)
    if not input_info or not input_info.get('productName'):
        return []

    product_name     = input_info['productName']
    base_sales_price = input_info['salesPrice']

    all_codes = get_all_options_by_product_name(product_name)
    if not all_codes:
        return []

    inventory_map = get_inventory_by_option_codes(all_codes)  # { code: stockUnit, ... }
    detail_map    = get_options_detail_by_codes(all_codes)    # { code: {optionName, salesPrice, ...}, ... }

    results = []
    for code in all_codes:
        detail = detail_map.get(code)
        if not detail:
            continue

        stock_unit = inventory_map.get(code, 0)

        # (1) 판매가가 동일해야 함
        # (2) 재고 >= needed_qty
        # (3) 재고 0은 제외
        if detail['salesPrice'] == base_sales_price and stock_unit >= needed_qty and stock_unit > 0:
            results.append({
                "optionName": detail['optionName'],
                "optionCode": code,
                "stock": stock_unit
            })

    return results


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



def fetch_naver_products(account_info):

    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        logger.error(f"{account_info['names'][0]}: 액세스 토큰 발급 실패!")
        return False, "토큰 발급 실패"

    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # 페이지네이션 설정
    PAGE_SIZE = 50   # 1회당 가져올 상품 개수
    MAX_RETRIES = 3

    all_products = []  # 모든 페이지에서 가져온 상품 누적 리스트
    current_page = 1
    total_pages = 1    # 일단 1로 시작 (실제 API 응답에서 totalElements 활용 가능)
    
    while True:
        payload = {
            "searchKeywordType": "SELLER_CODE",
            "productStatusTypes": ["SALE","OUTOFSTOCK"],
            "page": current_page,
            "size": PAGE_SIZE,
            "orderType": "NO",
        }

        # logger.debug(f"[fetch_naver_products] Request(page={current_page}) => {url}, payload={payload}")

        retry_count = 0
        while retry_count < MAX_RETRIES:
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30,proxies=proxies)
                # logger.debug(f"[fetch_naver_products] status_code={resp.status_code}")
                # logger.debug(f"[fetch_naver_products] response snippet => {resp.text[:300]}")

                # 1) 응답 헤더에서 남은 호출 횟수 확인 (없으면 -1)
                remain_str = resp.headers.get("GNCP-GW-RateLimit-Remaining")
                remain = int(remain_str) if remain_str else -1

                if resp.status_code == 429:
                    logger.warning("Rate Limit 발생! 10초 후 재시도...")
                    time.sleep(10)
                    retry_count += 1
                    continue

                elif resp.status_code == 200:
                    data = resp.json()
                    
                    # 이번 페이지 상품 목록
                    products = data.get("contents", [])
                    total_el = data.get("totalElements", 0)  # 전체 상품 수

                    # 누적
                    all_products.extend(products)

                    logger.info(
                        f"[{account_info['names'][0]}] page={current_page}, "
                        f"got {len(products)} products, totalElements={total_el} "
                        f"(남은 호출횟수={remain})"
                    )

                    # 남은 호출 횟수가 0에 가까우면 잠깐 대기
                    if remain >= 0 and remain < 1:
                        logger.info(f"남은 호출 횟수가 {remain}, 1초 대기")
                        time.sleep(1)

                    # 다음 페이지로 넘어갈지 여부 결정
                    # (예) 이번 페이지에 상품이 PAGE_SIZE 미만이면 더 이상 페이지 없음
                    #     또는 total_el를 기준으로, 현재까지 누적 개수가 total_el 이상이면 중단
                    if len(products) < PAGE_SIZE or len(all_products) >= total_el:
                        # 모든 페이지 요청 완료
                        return True, all_products
                    else:
                        # 다음 페이지로 이동
                        current_page += 1
                        break  # inner while(재시도 루프) 를 탈출, 바깥 while 로 돌아감

                else:
                    # 200, 429 외의 상태코드
                    detail_msg = f"{resp.status_code}, {resp.text}"
                    logger.error(f"{account_info['names'][0]} 상품목록 조회 실패: {detail_msg}")
                    return False, detail_msg

            except requests.exceptions.RequestException as e:
                # 네트워크 예외, 타임아웃 등
                msg = f"{account_info['names'][0]} 상품목록 조회 중 예외 발생: {str(e)}"
                logger.error(msg)
                return False, msg
        
        # retry_count가 MAX_RETRIES에 도달하면 에러 처리
        if retry_count >= MAX_RETRIES:
            msg = f"{account_info['names'][0]} 429 재시도 {MAX_RETRIES}회 초과, 목록 조회 중단"
            logger.error(msg)
            return False, msg





def get_naver_minimal_product_info(account_info, origin_product_no):
    """
    네이버 원상품(OriginProduct) 상세 정보를 조회하고,
    대표이미지/판매가/재고수량/옵션정보 등을 추출해 dict로 반환.

    :param account_info: NAVER_ACCOUNTS 중 하나 (스토어별 client_id 등)
    :param origin_product_no: 조회할 원상품번호 (int)
    :return: (True, result_dict) or (False, 에러메시지)
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
            resp = requests.get(url, headers=headers, timeout=30,proxies=proxies)

            if resp.status_code == 429:
                # 재시도
                time.sleep(10)
                retry_count += 1
                continue

            elif resp.status_code == 200:
                data = resp.json()
                # ↓↓↓ JSON을 예쁘게 정렬하여 출력
                # logger.debug(
                #     "[DETAIL] originNo=%s response data:\n%s",
                #     origin_product_no,
                #     json.dumps(data, ensure_ascii=False, indent=2)  # 여기서 JSON 예쁘게 정렬
                # )

                result = {}
                origin_prod = data.get("originProduct", {})

                sale_price = origin_prod.get("salePrice")
                stock_qty  = origin_prod.get("stockQuantity")

                images_part = origin_prod.get("images", {})
                rep_img_dict = images_part.get("representativeImage", {})

                detail_attr = origin_prod.get("detailAttribute", {})

                # 옵션 정보 파싱
                option_info   = detail_attr.get("optionInfo", {})
                option_combos = option_info.get("optionCombinations", [])

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

                # sellerCodeInfo 파싱
                seller_code_dict = detail_attr.get("sellerCodeInfo", {})
                seller_mgmt_code = seller_code_dict.get("sellerManagerCode", "")

                # 최종 결과
                result["representativeImage"] = rep_img_dict
                result["salePrice"]          = sale_price
                result["stockQuantity"]      = stock_qty
                result["optionCombinations"] = option_rows
                result["sellerCodeInfo"]     = {
                    "sellerManagerCode": seller_mgmt_code
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
    2) 각 상품별로 get_naver_minimal_product_info (단건조회) 호출
    3) "optionCombinations"까지 포함하여 detailed_list 에 담아서 return
    """

    import time

    # (A) 상품 목록
    is_ok, base_list = fetch_naver_products(account_info)
    if not is_ok:
        return False, base_list  # base_list가 에러 메시지

    detailed_list = []
    for i, item in enumerate(base_list, start=1):
        origin_no = item.get("originProductNo")
        ch_products = item.get("channelProducts", [])

        # product_name 우선 설정
        product_name = "(상품명없음)"
        if ch_products:
            product_name = ch_products[0].get("name", "(상품명없음)")

        # (2) ★ 여기서 discountedPrice 추출!
        discounted_price_api = 0
        if ch_products:
            discounted_price_api = ch_products[0].get("discountedPrice", 0)
            # 만약 mobileDiscountedPrice를 우선 사용하고 싶다면:
            # discounted_price_api = ch_products[0].get("mobileDiscountedPrice", 0) or ch_products[0].get("discountedPrice", 0)
        
        
        if not origin_no:
            # 상품번호가 없으면 skip
            continue

        # (B) 단건 상세 조회
        is_ok2, detail_info = get_naver_minimal_product_info(account_info, origin_no)
        if not is_ok2:
            # detail_info가 에러 메시지일 수 있음
            return False, detail_info

        # (C) merged dict - optionCombinations까지 넣어준다!
        merged = {
            "originProductNo": origin_no,
            "productName": product_name,
            "representativeImage": detail_info.get("representativeImage"),
            "salePrice": detail_info.get("salePrice"),
            "discountedPrice": discounted_price_api,   # ★ NEW
            "stockQuantity": detail_info.get("stockQuantity"),
            "sellerCodeInfo": detail_info.get("sellerCodeInfo"),
            "optionCombinations": detail_info.get("optionCombinations", []),
        }

        detailed_list.append(merged)

        # logger.debug(
        #     "[DEBUG fetch_naver_products_with_details] item=%s => merged=%s",
        #     item, merged
        # )

        # 각 상품 조회 후 1초 쉬기 (429 방지)
        time.sleep(1)

    logger.info(
        "[fetch_naver_products_with_details] 최종 detailed_list 개수=%d",
        len(detailed_list)
    )
    return True, detailed_list



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


def fetch_coupang_all_seller_products(account_info, max_per_page=150):
    """
    쿠팡 등록상품 목록 '페이징' 조회.
    '최신 10개'만 가져오려면, 아래에서 all_products -> slice
    """
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

        # 기존의 상세 endpoint 로그는 주석 처리
        # logger.debug(f"[fetch_coupang_all_seller_products] endpoint={endpoint}")
        retry_count = 0

        while True:
            try:
                resp = requests.get(endpoint, headers=headers, timeout=30)
            except requests.exceptions.Timeout:
                if retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"[fetch_coupang_all_seller_products] Timeout → 재시도 {retry_count}/{max_retries}")
                    time.sleep(0.1)
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
                data_json = resp.json()

                # ★★ 여기서 “API로 받아온 JSON”만 이쁘게 로그로 출력 ★★
                # logger.debug(
                #     "[fetch_coupang_all_seller_products] Response JSON:\n%s",
                #     json.dumps(data_json, ensure_ascii=False, indent=2)
                # )

                code = data_json.get("code")
                if code != "SUCCESS":
                    msg = f"[fetch_coupang_all_seller_products] code != SUCCESS, raw={data_json}"
                    logger.error(msg)
                    return False, msg

                data_list = data_json.get("data", [])
                all_products.extend(data_list)

                # 기존의 페이지 수/누적 개수 로그는 주석 처리
                # logger.debug(
                #     f"[fetch_coupang_all_seller_products] 이번 페이지 상품 수={len(data_list)}, "
                #     f"누적={len(all_products)}"
                # )

                next_token = data_json.get("nextToken", "")
                if not next_token:
                    # logger.debug("[fetch_coupang_all_seller_products] nextToken이 없어 종료.")
                    break
                else:
                    # logger.debug(f"[fetch_coupang_all_seller_products] nextToken={next_token} → 다음 페이지 조회")
                    break
            else:
                try:
                    err_json = resp.json()
                except:
                    err_json = {}
                # msg = f"[fetch_coupang_all_seller_products] HTTP {resp.status_code}, text={resp.text}"
                logger.error(msg)
                return False, msg

        if not next_token:
            # 더 이상 페이지 없음
            break

        # Rate limit 고려
        time.sleep(0.1)

    # logger.info(f"[fetch_coupang_all_seller_products] 최종 상품 수={len(all_products)}")

    # (C) '최근 상품' 10개만 slice → 여기서는 5개만 예시
    recent_10 = all_products[:1000]
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

            # ★★ 여기서 “API로 받아온 JSON”만 이쁘게 로그로 출력 ★★
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

def get_coupang_item_inventories(account_info, vendor_item_id):
    """
    옵션ID(vendorItemId)로 재고/가격 조회.
    GET /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/inventories
    """
    access_key = account_info.get('access_key')
    secret_key = account_info.get('secret_key')
    if not (access_key and secret_key):
        msg = f"{account_info['names'][0]}: Coupang API 계정정보 누락!"
        logger.error(msg)
        return False, msg

    method = "GET"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendor_item_id}/inventories"
    query_params = {}

    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)

    host = "https://api-gateway.coupang.com"
    endpoint = f"{host}{url_path}"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        ),
    }

    logger.debug(f"[get_coupang_item_inventories] GET {endpoint}")

    try:
        resp = requests.get(endpoint, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            # logger.debug(f"[get_coupang_item_inventories] resp.json()={data}")
            code = data.get("code")
            if code != "SUCCESS":
                msg = f"[get_coupang_item_inventories] code != SUCCESS, raw={data}"
                logger.error(msg)
                return False, msg
            
            item_data = data.get("data", {})
            logger.info(
                f"[get_coupang_item_inventories] vendorItemId={vendor_item_id} → "
                f"stock={item_data.get('amountInStock')}, salePrice={item_data.get('salePrice')}, onSale={item_data.get('onSale')}"
            )
            return True, item_data

        elif resp.status_code == 404:
            msg = f"[get_coupang_item_inventories] 404 Not Found: vendor_item_id={vendor_item_id}"
            logger.warning(msg)
            return False, msg
        
        else:
            msg = f"[get_coupang_item_inventories] status={resp.status_code}, text={resp.text}"
            logger.error(msg)
            return False, msg

    except requests.exceptions.RequestException as e:
        msg = f"[get_coupang_item_inventories] 요청 예외: {str(e)}"
        logger.error(msg)
        return False, msg


def fetch_coupang_seller_product_with_options(account_info, seller_product_id):
    """
    1) 쿠팡 get_coupang_seller_product() 호출 → 상품 상세 정보 조회
    2) items[...] 각 옵션에 대해:
       - vendorItemId: top-level → marketplaceItemData (rocketGrowth 무시)
       - externalVendorSku: top-level → marketplaceItemData → rocketGrowthItemData
         (마지막까지 없으면 "미매칭")
       - 재고/가격(get_coupang_item_inventories) 조회
       - Flatten
    3) 최종 flattened_list 반환
    """
    import json

    # 1) 상품 상세 조회
    is_ok, product_info = get_coupang_seller_product(account_info, seller_product_id)
    if not is_ok:
        # 실패 시 그대로 반환
        return False, product_info

    seller_product_name = product_info.get("displayProductName", "(상품명없음)")
    items = product_info.get("items", [])

    flattened_list = []

    for idx, item in enumerate(items, start=1):
        # (A) vendorItemId (top-level) 없으면 marketplaceItemData에서 fallback
        vendor_item_id = item.get("vendorItemId")
        if not vendor_item_id:
            vendor_item_id = item.get("marketplaceItemData", {}).get("vendorItemId")

        # 없으면 skip
        if not vendor_item_id:
            logger.warning(
                "[fetch_coupang_seller_product_with_options] No vendorItemId in top-level or marketplaceItemData "
                "→ skip itemName=%s (index=%d)",
                item.get("itemName"), idx
            )
            continue

        # (B) 대표이미지
        rep_image_url = ""
        image_list = item.get("images", [])
        if image_list:
            # 대표이미지(REPRESENTATION) 우선
            repr_img = next(
                (img for img in image_list if img.get("imageType") == "REPRESENTATION"),
                None
            )
            if repr_img:
                rep_image_url = repr_img.get("cdnPath", "")
            else:
                rep_image_url = image_list[0].get("cdnPath", "")
            if rep_image_url:
                rep_image_url = "https://img1a.coupangcdn.com/" + rep_image_url

        # (C) 재고/가격 조회
        is_ok2, inv_data = get_coupang_item_inventories(account_info, vendor_item_id)
        if not is_ok2:
            logger.warning(
                "[fetch_coupang_seller_product_with_options] 재고조회 실패 vendorItemId=%s → skip itemName=%s",
                vendor_item_id, item.get("itemName")
            )
            continue

        stock_qty  = inv_data.get("amountInStock", 0)
        sale_price = inv_data.get("salePrice", 0)

        # (D) externalVendorSku Fallback: top-level → marketplaceItemData → rocketGrowthItemData
        external_sku = item.get("externalVendorSku")
        if not external_sku:
            external_sku = item.get("marketplaceItemData", {}).get("externalVendorSku")
        if not external_sku:
            external_sku = item.get("rocketGrowthItemData", {}).get("externalVendorSku")
        if not external_sku:
            external_sku = "미매칭"

        # (E) Flattened dict
        item_name = item.get("itemName") or ""
        flattened_list.append({
            "optionID":            vendor_item_id,         # 최종 vendorItemId
            "optionSellerCode":    external_sku,           # externalVendorSku (fallback 적용)
            "representativeImage": rep_image_url,
            "optionName1":         item_name,
            "optionName2":         item_name,
            "productName":         seller_product_name,
            "optionStock":         stock_qty,
            "salePrice":           sale_price,
            "optionPrice":         sale_price,
            "originProductNo":     item.get("sellerProductItemId"),
        })

    # logger.debug(
    #     f"[fetch_coupang_seller_product_with_options] Flattened count={len(flattened_list)}"
    # )
    return True, flattened_list






def fetch_naver_option_stock(account_info, origin_product_no):
    """
    네이버 원상품(옵션) 재고/가격 조회 예시.
    GET /v2/products/origin-products/{originProductNo}
    Rate Limit(429) 발생 시, 최대 MAX_RETRIES 번 재시도.
    200 OK일 때 남은 호출 횟수(remain) 확인 → 0 이하이면 0.5초 대기.
    """

    import requests, time
    import logging
    logger = logging.getLogger(__name__)


    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        return False, "토큰 발급 실패"

    url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{origin_product_no}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    MAX_RETRIES = 3
    retry_count = 0

    while retry_count < MAX_RETRIES:
        try:
            resp = requests.get(url, headers=headers, timeout=30,proxies=proxies)

            if resp.status_code == 200:
                # ▼ 남은 호출 횟수 확인
                remain_str = resp.headers.get("GNCP-GW-RateLimit-Remaining")
                if remain_str is not None:
                    try:
                        remain = int(remain_str)
                    except ValueError:
                        remain = -1
                else:
                    remain = -1

                data = resp.json()
                origin_prod = data.get("originProduct", {})
                detail_attr = origin_prod.get("detailAttribute", {})
                option_info = detail_attr.get("optionInfo", {})
                combos = option_info.get("optionCombinations", [])

                # logger.debug(f"[fetch_naver_option_stock] combos={combos}, remain={remain}")

                # ▼ 남은 호출 횟수가 0 이하라면 잠깐 대기
                if remain >= 0 and remain < 1:
                    # logger.info(f"[fetch_naver_option_stock] 남은 호출 횟수={remain}, 0.5초 대기.")
                    time.sleep(0.5)

                return True, combos

            elif resp.status_code == 429:
                logger.warning(
                    "[fetch_naver_option_stock] Rate Limit 발생! "
                    f"10초 후 재시도... (retry={retry_count+1}/{MAX_RETRIES})"
                )
                time.sleep(10)
                retry_count += 1
                continue

            else:
                logger.warning(
                    f"[fetch_naver_option_stock] status={resp.status_code}, text={resp.text}"
                )
                return False, f"HTTP {resp.status_code}"

        except requests.RequestException as e:
            logger.error(f"[fetch_naver_option_stock] Exception: {e}")
            return False, str(e)

    # 여기까지 오면 429를 포함한 재시도 MAX_RETRIES 소진
    msg = "[fetch_naver_option_stock] 429 재시도 초과 or 기타 오류로 중단"
    logger.error(msg)
    return False, msg


def get_coupang_item_inventories(account_info, vendor_item_id):
    """
    GET /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/inventories
    -> 재고(amountInStock), salePrice, onSale

    200 OK 시 약간 대기 (예시) -> time.sleep(0.5)
    (쿠팡에서 남은 호출 횟수 헤더가 있다면, 그걸 확인 후 sleep하도록 수정해도 됨)
    """
    import requests, time, urllib
    import logging
    logger = logging.getLogger(__name__)

    access_key = account_info.get("access_key")
    secret_key = account_info.get("secret_key")
    vendor_id  = account_info.get("vendor_id")

    if not (access_key and secret_key):
        return False, "쿠팡 API 계정정보 누락!"

    method = "GET"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendor_item_id}/inventories"
    query_params = {}

    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)

    host = "https://api-gateway.coupang.com"
    canonical_query = '&'.join([f"{k}={urllib.parse.quote(str(v), safe='~')}" for k,v in query_params.items()])
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

    try:
        resp = requests.get(endpoint, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            # logger.debug(f"[get_coupang_item_inventories] resp.json={data}")
            code = data.get("code")
            if code != "SUCCESS":
                return False, data

            # ▼ (예시) 성공 시 0.5초 정도 대기
            # (쿠팡에서 RateLimit 헤더를 지원한다면, 여기서도 remain<1이면 sleep)
            time.sleep(0.1)

            return True, data.get("data", {})

        else:
            return False, f"HTTP {resp.status_code}, text={resp.text}"

    except requests.RequestException as e:
        logger.error(f"[get_coupang_item_inventories] Exception: {e}")
        return False, str(e)


def naver_update_option_stock(
    origin_no,
    option_id,
    new_stock=0,
    platform_name=None,
    keep_price=0,
    base_sale_price=0
):
    """
    네이버 옵션 재고=0 (품절) 
    → 'price' 필드를 제거하고, stockQuantity만 업데이트.
    """
    import logging, requests
    logger = logging.getLogger(__name__)

    if not platform_name:
        return False, "[naver_update_option_stock] platform_name이 없습니다."

    # (A) NAVER_ACCOUNTS에서 계정 찾기
    account_info = None
    for acct in NAVER_ACCOUNTS:
        if platform_name in acct['names']:
            account_info = acct
            break

    if not account_info:
        return False, f"[naver_update_option_stock] '{platform_name}' 계정을 NAVER_ACCOUNTS에서 찾을 수 없습니다."

    # (B) 토큰 발급
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        return False, "[naver_update_option_stock] 토큰 발급 실패"

    # (C) 기존 salePrice(상품 판매가) 설정
    #     여기서는 base_sale_price(정가), keep_price(옵션추가금)를 사용
    if keep_price is None:
        keep_price = 10000  # (예시) DB 값이 없으면 기본값

    body = {
        "productSalePrice": {
            "salePrice": base_sale_price  # 상품 기본가(정가 or 할인가)
        },
        "optionInfo": {
            "optionCombinations": [
                {
                    "id": int(option_id),
                    "price": keep_price,      # 이 옵션의 추가금(혹은 단독가)
                    "stockQuantity": new_stock
                }
            ]
        }
    }
    # logger.debug(f"[naver_update_option_stock] request body={body}")

    url = f"https://api.commerce.naver.com/external/v1/products/origin-products/{origin_no}/option-stock"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.put(url, headers=headers, json=body, timeout=30, proxies=proxies)
        # 네이버 서버 응답 로깅
        # logger.debug(f"[naver_update_option_stock] Naver response code={resp.status_code}, body={resp.text}")

        if resp.status_code == 200:
            data = resp.json()
            # logger.debug(f"[naver_update_option_stock] success data={data}")
            return True, "OK"
        else:
            logger.warning(
                f"[naver_update_option_stock] status={resp.status_code}, text={resp.text}"
            )
            return False, f"HTTP {resp.status_code}, text={resp.text}"

    except requests.RequestException as e:
        # 요청 예외 발생 시 에러 로깅
        logger.error(f"[naver_update_option_stock] 예외: {e}", exc_info=True)
        return False, str(e)

def coupang_update_item_stock(vendor_item_id, new_stock=0, platform_name=None):
    """
    쿠팡 옵션 재고 변경 예시
    PUT /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/{quantity}
    (body 없음)
    """
    import logging, requests
    logger = logging.getLogger(__name__)

    # (1) COUPANG_ACCOUNTS + generate_coupang_signature 가져오기

    if not platform_name:
        return False, "[coupang_update_item_stock] platform_name이 없습니다."

    # (2) 쿠팡 계정 찾기
    account_info = None
    for acct in COUPANG_ACCOUNTS:
        if platform_name in acct.get('names', []):
            account_info = acct
            break

    if not account_info:
        return False, f"[coupang_update_item_stock] '{platform_name}' 계정을 COUPANG_ACCOUNTS에서 찾을 수 없습니다."

    access_key = account_info.get("access_key")
    secret_key = account_info.get("secret_key")
    if not (access_key and secret_key):
        return False, "[coupang_update_item_stock] 쿠팡 API 계정정보 누락!"

    # (3) 시그니처 생성
    # 예: PUT /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/{quantity}
    method = "PUT"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendor_item_id}/quantities/{new_stock}"

    query_params = {}  # 필요시 세팅
    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)

    host = "https://api-gateway.coupang.com"
    import urllib
    canonical_query = '&'.join(
        f"{k}={urllib.parse.quote(str(v), safe='~')}" for k, v in query_params.items()
    )
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

    # logger.debug(
    #     f"[coupang_update_item_stock] vendor_item_id={vendor_item_id}, new_stock={new_stock}, "
    #     f"platform={platform_name}, endpoint={endpoint}"
    # )

    try:
        resp = requests.put(endpoint, headers=headers, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            code = data.get("code")
            if code == "SUCCESS":
                # logger.debug(f"[coupang_update_item_stock] success data={data}")
                return True, "OK"
            else:
                # logger.warning(f"[coupang_update_item_stock] code={code}, msg={data}")
                return False, data
        else:
            # logger.warning(
            #     f"[coupang_update_item_stock] HTTP {resp.status_code}, text={resp.text}"
            # )
            return False, f"HTTP {resp.status_code}, text={resp.text}"
    except requests.RequestException as e:
        # logger.error(f"[coupang_update_item_stock] 예외: {e}")
        return False, str(e)


def put_naver_option_stock_9999(origin_no, option_id, platform_name=None,base_sale_price=0,keep_price=0):
    """
    네이버 옵션 재고를 9999로 (가득 채우는) 예시.
    PUT /v1/products/origin-products/{originNo}/option-stock
    
    - 'price' 필드는 제거(가격은 건드리지 않음).
    - 'stockQuantity': 9999
    - platform_name을 통해 NAVER_ACCOUNTS 찾아 토큰 발급 후 호출.
    """

    import logging, requests
    logger = logging.getLogger(__name__)

    # NAVER_ACCOUNTS, fetch_naver_access_token 불러오기

    if not platform_name:
        return False, "[put_naver_option_stock_9999] platform_name이 없습니다."

    # (A) 네이버 계정 찾기
    account_info = None
    for acct in NAVER_ACCOUNTS:
        if platform_name in acct['names']:
            account_info = acct
            break

    if not account_info:
        return False, f"[put_naver_option_stock_9999] '{platform_name}' 계정을 NAVER_ACCOUNTS에서 찾을 수 없습니다."

    # (B) 토큰 발급
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        return False, "[put_naver_option_stock_9999] 토큰 발급 실패"

    body = {
        "productSalePrice": {
            "salePrice": base_sale_price
        },
        "optionInfo": {
            "optionCombinations": [
                {
                    "id": int(option_id),
                    "price": keep_price,       # 옵션 추가금
                    "stockQuantity": 9999
                }
            ]
        }
    }

    url = f"https://api.commerce.naver.com/external/v1/products/origin-products/{origin_no}/option-stock"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.put(url, headers=headers, json=body, timeout=30,proxies=proxies)
        if resp.status_code == 200:
            data = resp.json()
            logger.debug(f"[put_naver_option_stock_9999] success data={data}")
            return True, "OK"
        else:
            logger.warning(
                f"[put_naver_option_stock_9999] status={resp.status_code}, text={resp.text}"
            )
            return False, f"HTTP {resp.status_code}, text={resp.text}"
    except requests.RequestException as e:
        logger.error(f"[put_naver_option_stock_9999] 예외: {e}")
        return False, str(e)


def put_coupang_option_stock_9999(vendor_item_id, platform_name=None):
    """
    쿠팡 옵션 재고를 9999로 설정 예시.
    PUT /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/9999
    (body 없음)
    
    - platform_name으로 COUPANG_ACCOUNTS 찾아서 access_key/secret_key 세팅
    - 시그니처 생성 후 PUT
    """

    import logging, requests
    logger = logging.getLogger(__name__)


    if not platform_name:
        return False, "[put_coupang_option_stock_9999] platform_name이 없습니다."

    # (A) 쿠팡 계정 찾기
    account_info = None
    for acct in COUPANG_ACCOUNTS:
        if platform_name in acct.get('names', []):
            account_info = acct
            break

    if not account_info:
        return False, f"[put_coupang_option_stock_9999] '{platform_name}' 계정을 COUPANG_ACCOUNTS에서 찾을 수 없습니다."

    access_key = account_info.get("access_key")
    secret_key = account_info.get("secret_key")
    if not (access_key and secret_key):
        return False, "[put_coupang_option_stock_9999] 쿠팡 API 계정정보 누락!"

    # (B) 시그니처 생성
    method = "PUT"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendor_item_id}/quantities/9999"
    query_params = {}

    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)
    
    import urllib
    canonical_query = '&'.join(
        f"{k}={urllib.parse.quote(str(v), safe='~')}"
        for k,v in query_params.items()
    )
    host = "https://api-gateway.coupang.com"
    endpoint = f"{host}{url_path}"
    if canonical_query:
        endpoint += f"?{canonical_query}"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        )
    }

    logger.debug(
        f"[put_coupang_option_stock_9999] vendor_item_id={vendor_item_id}, platform={platform_name}, endpoint={endpoint}"
    )

    try:
        resp = requests.put(endpoint, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            code = data.get("code")
            if code == "SUCCESS":
                logger.debug(f"[put_coupang_option_stock_9999] success data={data}")
                return True, "OK"
            else:
                logger.warning(f"[put_coupang_option_stock_9999] code={code}, msg={data}")
                return False, data
        else:
            logger.warning(
                f"[put_coupang_option_stock_9999] HTTP {resp.status_code}, text={resp.text}"
            )
            return False, f"HTTP {resp.status_code}, text={resp.text}"
    except requests.RequestException as e:
        logger.error(f"[put_coupang_option_stock_9999] 예외: {e}")
        return False, str(e)


def get_coupang_seller_product_info(account_info, seller_product_id):
    """
    등록상품ID(seller_product_id)로 쿠팡 상품 정보를 조회.
    (GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId})

    :param account_info: 쿠팡 API 계정 딕셔너리 (access_key, secret_key, names 등)
    :param seller_product_id: 등록상품ID (int or str)
    :return: (True, product_data) or (False, 에러메시지)
    
    Response 예시:
    {
      "code": "SUCCESS",
      "message": "",
      "data": {
        "sellerProductId": 1234567,
        "statusName": "승인완료",
        "displayCategoryCode": 115721,
        "sellerProductName": "예시 상품명",
        "vendorId": "A1234",
        "saleStartedAt": "2021-01-01T00:00:00",
        "saleEndedAt": "2099-12-31T23:59:59",
        "displayProductName": "노출상품명",
        "brand": "브랜드명",
        "generalProductName": "기본 상품명",
        "productGroup": "상품군",
        "deliveryMethod": "SEQUENCIAL",
        ...
        "items": [
          {
            "sellerProductItemId": 123456789,
            "vendorItemId": 987654321,  # 옵션ID
            "itemName": "옵션명",
            "salePrice": 19900,
            "maximumBuyCount": 100,
            ...
          },
          ...
        ]
      }
    }
    """
    import logging, requests
    from .api_clients import generate_coupang_signature

    logger = logging.getLogger(__name__)

    access_key = account_info.get('access_key')
    secret_key = account_info.get('secret_key')
    if not (access_key and secret_key):
        msg = f"{account_info['names'][0]}: Coupang API 계정(access_key/secret_key) 누락!"
        logger.error(msg)
        return False, msg

    method = "GET"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
    query_params = {}

    # 시그니처 생성
    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)

    host = "https://api-gateway.coupang.com"
    endpoint = f"{host}{url_path}"  # query_params가 없으므로 단순 URL

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        ),
    }

    logger.debug(f"[get_coupang_seller_product_info] GET {endpoint}")

    try:
        resp = requests.get(endpoint, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            code = data.get("code")
            if code != "SUCCESS":
                msg = f"[get_coupang_seller_product_info] code != SUCCESS, raw={data}"
                logger.error(msg)
                return False, msg
            
            product_data = data.get("data", {})
            logger.info(
                f"[get_coupang_seller_product_info] sellerProductId={seller_product_id}, "
                f"statusName={product_data.get('statusName')}, items.len={len(product_data.get('items', []))}"
            )
            return True, product_data
        
        elif resp.status_code == 404:
            msg = f"[get_coupang_seller_product_info] 404 Not Found: seller_product_id={seller_product_id}"
            logger.warning(msg)
            return False, msg
        
        else:
            msg = f"[get_coupang_seller_product_info] status={resp.status_code}, text={resp.text}"
            logger.error(msg)
            return False, msg

    except requests.exceptions.RequestException as e:
        msg = f"[get_coupang_seller_product_info] 요청 예외: {str(e)}"
        logger.error(msg)
        return False, msg
