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