# api_clients.py

import requests
import time
import base64
import bcrypt
import hmac
import hashlib
import urllib.parse
from datetime import datetime, timedelta, timezone  # timezone 추가
import logging
from decouple import config
import json
import pytz
import pandas as pd
from .maps import product_order_status_map
from proxy_config import proxies

logger = logging.getLogger(__name__)

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
    response = requests.post(url, data=params, proxies=proxies)
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

def fetch_naver_returns(account_info):
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        return []

    headers = {
        'Authorization': f'Bearer {access_token}',
    }

    kst = timezone(timedelta(hours=9))
    end_date = datetime.now(tz=kst)
    start_date = end_date - timedelta(days=5)
    delta = timedelta(hours=24)

    target_claim_statuses = ['EXCHANGE_REQUEST', 'COLLECT_DONE', 'RETURN_REQUEST', 'RETURN_DONE', 'EXCHANGE_DONE']
    all_product_order_ids = []
    max_retries = 3

    current_date = start_date
    while current_date < end_date:
        last_changed_from = current_date.isoformat(timespec='milliseconds')
        last_changed_to = (current_date + delta).isoformat(timespec='milliseconds')

        params = {
            'lastChangedFrom': last_changed_from,
            'lastChangedTo': last_changed_to,
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
                        timeout=30,  # timeout 설정
                        proxies=proxies
                    )
                    if response.status_code == 200:
                        data = response.json()
                        last_change_statuses = data.get('data', {}).get('lastChangeStatuses', [])

                        for order in last_change_statuses:
                            claim_status = order.get('claimStatus')
                            product_order_id = order.get('productOrderId')
                            if claim_status and claim_status in target_claim_statuses:
                                all_product_order_ids.append(product_order_id)

                        more = data.get('data', {}).get('more', {})
                        if more:
                            more_sequence = more.get('moreSequence')
                            params['lastChangedFrom'] = more.get('moreFrom')
                            time.sleep(1)
                        else:
                            # 다음 페이지 없음
                            break
                        retry_count = 0
                    elif response.status_code == 429:
                        if retry_count < max_retries:
                            retry_count += 1
                            logger.error(f"{account_info['names'][0]} API 호출 제한에 걸렸습니다. {retry_count}/{max_retries}회 재시도")
                            time.sleep(5)
                            continue
                        else:
                            logger.error(f"{account_info['names'][0]} API 호출 제한 반복 발생, 이 구간 처리 중단")
                            break
                    else:
                        logger.error(f"{account_info['names'][0]} 변경 상품 주문 내역 조회 실패: {response.status_code}, {response.text}")
                        break
                    break
                except requests.exceptions.Timeout:
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"{account_info['names'][0]} 변경 상품 주문 내역 조회 타임아웃 발생. 재시도 {retry_count}/{max_retries}")
                        time.sleep(3)
                        continue
                    else:
                        logger.error(f"{account_info['names'][0]} 변경 상품 주문 내역 조회 타임아웃 반복 발생, 이 구간 처리 중단")
                        break
                except requests.exceptions.RequestException as e:
                    logger.error(f"요청 중 예외 발생: {e}")
                    break

            else:
                # while True 블록이 break 없이 끝나면 here
                pass
            break  # 더 이상 nextToken이 없거나 실패 시 상위 while 탈출

        current_date += delta

    returns = fetch_naver_order_details(account_info, all_product_order_ids)
    result = {
        "code": 200,
        "message": "OK",
        "data": returns
    }
    # json_result = json.dumps(result, ensure_ascii=False, indent=4)
    return returns

def fetch_naver_order_details(account_info, product_order_ids):
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


def approve_naver_return(account_info, product_order_id):
    print(f"플랫폼(계정): {account_info['names'][0] if 'names' in account_info else '알 수 없음'} - 주문번호: {product_order_id}")
    access_token = fetch_naver_access_token(account_info)

    if not access_token:
        return False, "토큰 발급 실패"

    url = f"https://api.commerce.naver.com/external/v1/pay-order/seller/product-orders/{product_order_id}/claim/return/approve"
    headers = {
        'Authorization': f'Bearer {access_token}'
        # 문서 예시에 따르면 Content-Type나 body는 따로 필요 없는 것으로 보임
        # 필요하다면 'Content-Type': 'application/json' 추가
    }

    print("API 요청 URL:", url)  # 디버깅용 로그
    response = requests.post(url, headers=headers, proxies=proxies)
    print("API 응답 코드:", response.status_code)  # 디버깅용 로그
    print("API 응답 내용:", response.text)  # 디버깅용 로그

    if response.status_code == 200:
        data = response.json()
        success_ids = data.get('data', {}).get('successProductOrderIds', [])
        if product_order_id in success_ids:
            return True, "반품 승인 성공"
        else:
            fail_info = data.get('data', {}).get('failProductOrderInfos', [])
            return False, f"반품 승인 실패: {fail_info}"
    else:
        return False, f"API 호출 실패: {response.status_code}, {response.text}"


def get_product_order_details(account_info, product_order_ids):
    print(account_info, product_order_ids)
    logger.debug("get_product_order_details 호출")
    logger.debug(f"account_info: {account_info}")
    logger.debug(f"product_order_ids: {product_order_ids}")

    # product_order_ids가 문자열일 경우 리스트로 변환
    if isinstance(product_order_ids, str):
        product_order_ids = [product_order_ids.strip()]

    # product_order_ids가 리스트이지만 유효한 문자열이 아닐 경우 정제
    elif isinstance(product_order_ids, list):
        product_order_ids = [str(p).strip() for p in product_order_ids if p]

    if not product_order_ids:
        logger.error("유효한 product_order_ids가 없습니다.")
        return {
            'success': False,
            'message': '유효한 product_order_ids를 제공해주세요.'
        }

    access_token = fetch_naver_access_token(account_info)
    logger.debug(f"access_token: {access_token}")

    if not access_token:
        logger.error("액세스 토큰을 가져오지 못했습니다.")
        return {'success': False, 'message': '액세스 토큰 불가'}

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    url = 'https://api.commerce.naver.com/external/v1/pay-order/seller/product-orders/query'
    payload = {
        "productOrderIds": product_order_ids,
        "quantityClaimCompatibility": True
    }

    logger.debug(f"요청 URL: {url}")
    logger.debug(f"요청 headers: {headers}")
    logger.debug(f"요청 payload: {payload}")

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30, proxies=proxies)
        logger.debug(f"응답 상태코드: {response.status_code}")
        logger.debug(f"응답 본문: {response.text}")

        response.raise_for_status()
    except requests.HTTPError as he:
        logger.error(f"상품 주문 상세 조회 중 HTTP 오류 발생: {he}")
        logger.error(f"응답 본문: {response.text if response else 'No Response'}")
        return {'success': False, 'message': f"상품 주문 상세 조회 실패(HTTP Error): {he}, 응답: {response.text if response else 'No Response'}"}
    except requests.RequestException as e:
        logger.error(f"상품 주문 상세 조회 중 요청 예외 발생: {e}")
        return {'success': False, 'message': f"상품 주문 상세 조회 실패(Request Exception): {e}"}

    data = response.json()
    result_data = data.get('data', [])
    details_list = []
    for item in result_data:
        product_order = item.get('productOrder', {})
        productOrderId = product_order.get('productOrderId', '')
        productOrderStatus = product_order.get('productOrderStatus', 'N/A')
        claimStatus = item.get('claimStatus', 'N/A')
        claimType = item.get('claimType', 'N/A')

        details_list.append({
            'productOrderId': productOrderId,
            'productOrderStatus': productOrderStatus,
            'claimStatus': claimStatus,
            'claimType': claimType,
        })

    # 여기서 productOrderStatus를 한글로 매핑
    for detail in details_list:
        original_status = detail['productOrderStatus']
        detail['productOrderStatus'] = product_order_status_map.get(original_status, original_status)

    logger.debug(f"파싱된 details_list: {details_list}")

    return {'success': True, 'details': details_list}


def dispatch_naver_exchange(
    account_info,
    product_order_id,
    re_delivery_method="DELIVERY",
    re_delivery_company=None,
    re_delivery_tracking_number=None
):
    """
    교환 재배송 처리 (Exchange Dispatch) API 호출 함수
    POST /v1/pay-order/seller/product-orders/{productOrderId}/claim/exchange/dispatch
    """
    print("=== [DEBUG] dispatch_naver_exchange 함수 진입 ===")
    print(f"[DEBUG] account_info: {account_info}")
    print(f"[DEBUG] product_order_id: {product_order_id}")
    print(f"[DEBUG] re_delivery_method: {re_delivery_method}")
    print(f"[DEBUG] re_delivery_company: {re_delivery_company}")
    print(f"[DEBUG] re_delivery_tracking_number: {re_delivery_tracking_number}")

    if not account_info:
        print("[DEBUG] account_info가 None 혹은 빈 상태입니다.")
        return False, "account_info가 유효하지 않습니다."

    # 플랫폼(계정) 및 주문번호 로그
    account_names = account_info['names'] if 'names' in account_info else ["알 수 없음"]
    print(f"[DEBUG] 플랫폼(계정) 후보: {account_names}, 실제 사용: {account_names[0] if account_names else '알 수 없음'} / 주문번호: {product_order_id}")

    # 액세스 토큰 발급
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        print("[DEBUG] 액세스 토큰 발급 실패")
        return False, "토큰 발급 실패"

    print("[DEBUG] 액세스 토큰 발급 성공:", access_token)

    # API 요청 URL 및 헤더
    url = f"https://api.commerce.naver.com/external/v1/pay-order/seller/product-orders/{product_order_id}/claim/exchange/dispatch"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    # Request Body 구성
    payload = {
        "reDeliveryMethod": re_delivery_method
    }
    if re_delivery_company:
        payload["reDeliveryCompany"] = re_delivery_company
    if re_delivery_tracking_number:
        payload["reDeliveryTrackingNumber"] = re_delivery_tracking_number

    print("[DEBUG] 교환 재배송 API 요청 URL:", url)
    print("[DEBUG] 교환 재배송 API 요청 Headers:", headers)
    print("[DEBUG] 교환 재배송 API 요청 Payload:", payload)

    # API 호출
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30, proxies=proxies)
    except requests.RequestException as e:
        print("[DEBUG] API 요청 중 예외 발생:", e)
        return False, f"API 요청 실패 (RequestException): {e}"

    print("[DEBUG] API 응답 코드:", response.status_code)
    print("[DEBUG] API 응답 내용:", response.text)

    # 상태코드에 따른 처리
    if response.status_code == 200:
        data = response.json()
        print("[DEBUG] 응답 JSON 파싱 완료:", data)

        # successProductOrderIds 와 failProductOrderInfos 구조는 approve_naver_return 참고
        success_ids = data.get('data', {}).get('successProductOrderIds', [])
        fail_info = data.get('data', {}).get('failProductOrderInfos', [])

        print("[DEBUG] successProductOrderIds:", success_ids)
        print("[DEBUG] failProductOrderInfos:", fail_info)

        if product_order_id in success_ids:
            print("[DEBUG] 교환 재배송 처리 성공!")
            return True, "교환 재배송 처리 성공"
        else:
            print("[DEBUG] 교환 재배송 처리 실패 (failProductOrderInfos 존재 또는 successIds에 없음)")
            return False, f"교환 재배송 처리 실패: {fail_info}"

    else:
        # 200 이외의 상태코드
        msg = f"API 호출 실패: {response.status_code}, {response.text}"
        print("[DEBUG]", msg)
        return False, msg


def generate_coupang_signature(method, url_path, query_params, secret_key):
    datetime_now = time.strftime('%y%m%dT%H%M%SZ', time.gmtime())

    # Canonical Query String 생성
    sorted_query_params = sorted(query_params.items())
    canonical_query_string = '&'.join(
        [f"{key}={urllib.parse.quote(str(value), safe='~')}" for key, value in sorted_query_params]
    )

    # 메시지 구성
    message = datetime_now + method + url_path + canonical_query_string

    # HMAC 서명 생성
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature, datetime_now


def fetch_coupang_returns(account_info):
    method = 'GET'
    url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{account_info['vendor_id']}/returnRequests"
    status_list = ['UC', 'CC', 'PR']  # 필요한 모든 상태 값
    all_returns = []

    total_days = 5
    max_retries = 3
    # 하루 단위로 조회, 과거 21일

    for status in status_list:
        for i in range(total_days):
            from_date = (datetime.utcnow() - timedelta(days=(i+1))).strftime('%Y-%m-%d')
            to_date = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')

            next_token = ''
            retry_count = 0

            while True:
                query_params = {
                    'createdAtFrom': from_date,
                    'createdAtTo': to_date,
                    'status': status,
                    'maxPerPage': 50,
                }

                if next_token:
                    query_params['nextToken'] = next_token

                signature, datetime_now = generate_coupang_signature(
                    method, url_path, query_params, account_info['secret_key']
                )

                authorization = (
                    f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
                    f"signed-date={datetime_now}, signature={signature}"
                )

                headers = {
                    'Content-Type': 'application/json;charset=UTF-8',
                    'Authorization': authorization,
                }

                encoded_query_string = urllib.parse.urlencode(sorted(query_params.items()), safe='~')
                full_url = f"https://api-gateway.coupang.com{url_path}?{encoded_query_string}"

                try:
                    response = requests.get(full_url, headers=headers, timeout=30)  # timeout 설정
                    response_json = response.json()
                except requests.exceptions.Timeout:
                    # 요청 타임아웃 시 재시도
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"{account_info['names'][0]} 반품 목록 조회 타임아웃 발생. 재시도 {retry_count}/{max_retries}, 상태({status}), 기간({from_date}~{to_date})")
                        time.sleep(3)
                        continue
                    else:
                        logger.error(f"{account_info['names'][0]} 반품 목록 조회 타임아웃 반복 발생, 상태({status}), 기간({from_date}~{to_date}) 처리 중단")
                        break
                except json.JSONDecodeError:
                    logger.error(f"응답 본문이 JSON 형식이 아닙니다: {response.text}")
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"요청 중 예외 발생: {e}")
                    break

                if response.status_code == 200:
                    data = response_json
                    returns = data.get('data', [])
                    all_returns.extend(returns)

                    next_token = data.get('nextToken')
                    if not next_token:
                        # 다음 페이지 없음
                        break
                    # 다음 페이지 존재 시
                    retry_count = 0
                else:
                    # 에러 응답 처리
                    error_code = response_json.get('code')
                    error_message = response_json.get('message', '')

                    if error_code == 'ERROR' and 'Request timed out' in error_message:
                        if retry_count < max_retries:
                            retry_count += 1
                            logger.warning(f"{account_info['names'][0]} 반품 목록 조회 타임아웃 발생. 재시도 {retry_count}/{max_retries}, 상태({status}), 기간({from_date}~{to_date})")
                            time.sleep(3)
                            continue
                        else:
                            logger.error(f"{account_info['names'][0]} 반품 목록 조회 타임아웃 반복 발생, 상태({status}), 기간({from_date}~{to_date}) 처리 중단")
                            break
                    else:
                        logger.error(f"{account_info['names'][0]} 반품 목록 조회 실패 (상태: {status}, 기간: {from_date}~{to_date}): {response.status_code}, {response.text}")
                        break

                # Rate Limit 고려
                time.sleep(0.5)

    logger.info(f"{account_info['names'][0]}에서 가져온 총 쿠팡 반품 데이터 수: {len(all_returns)}")
    return all_returns


def fetch_coupang_exchanges(account_info):
    method = 'GET'
    url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{account_info['vendor_id']}/exchangeRequests"
    query_params = {
        'createdAtFrom': (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S'),
        'createdAtTo': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S'),
    }

    signature, datetime_now = generate_coupang_signature(
        method, url_path, query_params, account_info['secret_key']
    )

    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
        f"signed-date={datetime_now}, signature={signature}"
    )

    headers = {
        'Content-Type': 'application/json',
        'Authorization': authorization,
    }

    encoded_query_string = urllib.parse.urlencode(sorted(query_params.items()), safe='~')
    full_url = f"https://api-gateway.coupang.com{url_path}?{encoded_query_string}"

    try:
        response = requests.get(full_url, headers=headers, timeout=30)  # timeout 설정
        response_json = response.json()
    except requests.exceptions.Timeout:
        logger.error(f"{account_info['names'][0]} 교환 목록 조회 타임아웃 발생")
        return []
    except json.JSONDecodeError:
        logger.error(f"응답 본문이 JSON 형식이 아닙니다: {response.text}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"요청 중 예외 발생: {e}")
        return []

    if response.status_code == 200:
        data = response_json
        logger.info(f"{account_info['names'][0]}에서 가져온 쿠팡 교환 데이터 수: {len(data.get('data', []))}")
        return data.get('data', [])
    else:
        logger.error(f"{account_info['names'][0]} 교환 목록 조회 실패: {response.status_code}, {response.text}")
        return []


def get_seller_product_item_id(seller_product_id, account_info):
    method = 'GET'
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
    query_params = {}

    # 서명 생성
    signature, datetime_now = generate_coupang_signature(
        method, url_path, query_params, account_info['secret_key']
    )

    # Authorization 헤더 생성
    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
        f"signed-date={datetime_now}, signature={signature}"
    )

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'Authorization': authorization,
    }

    full_url = f"https://api-gateway.coupang.com{url_path}"

    response = requests.get(full_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        # 상품 옵션 리스트에서 필요한 정보를 추출
        items = data.get('data', {}).get('items', [])
        if items:
            seller_product_item_id = items[0].get('sellerProductItemId')
            return seller_product_item_id
    else:
        logger.error(f"상품 조회 실패: {response.status_code}, {response.text}")
    return None


def get_order_detail(order_id, account_info):
    method = 'GET'
    vendor_id = account_info['vendor_id']
    url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/{order_id}/ordersheets"
    query_params = {}

    # 서명 생성
    signature, datetime_now = generate_coupang_signature(
        method, url_path, query_params, account_info['secret_key']
    )

    # Authorization 헤더 생성
    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
        f"signed-date={datetime_now}, signature={signature}"
    )

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'Authorization': authorization,
    }

    full_url = f"https://api-gateway.coupang.com{url_path}"

    response = requests.get(full_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        data_list = data.get('data', [])
        if data_list:
            order_data = data_list[0]
            invoice_number = order_data.get('invoiceNumber', ' ')
            delivered_date = order_data.get('deliveredDate', ' ')
            return invoice_number, delivered_date
        else:
            logger.error(f"발주서 데이터가 없습니다: {order_id}")
            return ' ', ' '
    else:
        logger.error(f"발주서 조회 실패: {response.status_code}, {response.text}")
        return ' ', ' '

def get_external_vendor_sku(seller_product_id, vendor_item_id, account_info):
    method = 'GET'
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
    query_params = {}
    
    # 서명 생성
    signature, datetime_now = generate_coupang_signature(
        method, url_path, query_params, account_info['secret_key']
    )
    
    # Authorization 헤더 생성
    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
        f"signed-date={datetime_now}, signature={signature}"
    )
    
    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'Authorization': authorization,
    }
    
    full_url = f"https://api-gateway.coupang.com{url_path}"
    
    response = requests.get(full_url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        items = data.get('data', {}).get('items', [])
        for item in items:
            if item.get('vendorItemId') == vendor_item_id:
                external_vendor_sku = item.get('externalVendorSku')
                return external_vendor_sku
        logger.error(f"Vendor Item ID {vendor_item_id}에 해당하는 옵션을 찾을 수 없습니다.")
    else:
        logger.error(f"상품 조회 실패: {response.status_code}, {response.text}")
    return None
    
def get_return_request_details(vendor_id, receipt_id, account_info):
    method = 'GET'
    url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/returnRequests/{receipt_id}"
    query_params = {}

    # 서명 생성
    signature, datetime_now = generate_coupang_signature(
        method, url_path, query_params, account_info['secret_key']
    )

    # Authorization 헤더 생성
    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={account_info['access_key']}, "
        f"signed-date={datetime_now}, signature={signature}"
    )

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'Authorization': authorization,
    }

    full_url = f"https://api-gateway.coupang.com{url_path}"

    response = requests.get(full_url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        logger.info(f"반품 요청 단건 조회 응답: {data}")
        return data
    else:
        logger.error(f"반품요청 단건 조회 실패: {response.status_code}, {response.text}")
        return None
# 전체 데이터 조회 함수
def fetch_all_data():
    # 네이버 반품 및 교환 데이터 수집
    for account_info in NAVER_ACCOUNTS:
        returns = fetch_naver_returns(account_info)
        # 반환된 데이터 처리 로직 추가 (예: 데이터베이스 저장 등)

    # 쿠팡 반품 및 교환 데이터 수집
    for account_info in COUPANG_ACCOUNTS:
        # 반품 데이터 수집
        returns = fetch_coupang_returns(account_info)
        # 반환된 데이터 처리 로직 추가

        # 교환 데이터 수집
        exchanges = fetch_coupang_exchanges(account_info)
        # 반환된 데이터 처리 로직 추가

# 필요한 경우 main 함수 또는 뷰에서 fetch_all_data()를 호출하여 데이터 수집 시작


ST_API_KEY = config('ST_API_KEY', default=None)
ST_SECRET_KEY = config('ST_SECRET_KEY', default=None)

REQUEST_URL_INVENTORY = 'https://shared-api.sellertool.io/api/inventories/search/stocks-by-optionCodes'
REQUEST_URL_OPTION_BY_CODE = 'https://shared-api.sellertool.io/api/product-options/search/by-optionCodes'
REQUEST_URL_OPTIONS = 'https://shared-api.sellertool.io/api/product-options'
REQUEST_URL_HOURLY_SALES = 'https://shared-api.sellertool.io/api/analytics/hourlySales'  # ★ 추가

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

def get_hourly_sales(option_codes, date_str, date_condition='CHANNEL_ORDER_DATE', diff_hours=9):
    """
    hourlySales API를 호출하여 시간대별 판매 정보를 가져온다.
    :param option_codes: list 형태의 옵션코드 배열
    :param date_str: 조회 날짜 (예: '2025-01-08')
    :param date_condition: 조회 기준 (기본값: 'CHANNEL_ORDER_DATE')
    :param diff_hours: UTC 기준 차이 (기본값: 9 → 한국)
    :return: 성공 시 list 형태 (시간대별 데이터), 실패 시 []
    """
    headers = get_headers()
    body = {
        "optionCodes": option_codes,
        "date": date_str, 
        "dateCondition": date_condition,
        "diffHours": diff_hours
    }
    try:
        response = requests.post(REQUEST_URL_HOURLY_SALES, headers=headers, data=json.dumps(body))

        logger.debug(f"hourlySales API status_code={response.status_code}")
        logger.debug(f"hourlySales API response text={response.text}")
        if response.status_code == 200:
            return response.json()  # 보통 list 반환 (예상)
        else:
            logger.error(f"hourlySales API Error: {response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"Exception on hourlySales API: {e}")
    return []
    pass

def get_hourly_sales_for_period(option_codes, start_date, end_date):
    """
    [핵심] start_date ~ end_date 사이의 모든 날짜를 루프 돌며
    매일 get_hourly_sales() API를 호출하여, '일자별 판매량'을 모은다.

    :param option_codes: list, 옵션코드 배열
    :param start_date: datetime.date or datetime, 기간 시작일
    :param end_date: datetime.date or datetime, 기간 종료일
    :return: list 형태 (예시):
      [
        {
          "date": "2025-01-01",
          "daily_total_units": 10,
          "detail": [   # 옵션코드별/시간대별 상세 등 원하면 추가
            {
              "optionCode": "...",
              "hourlySalesData": [
                {"hour": 0, "totalUnits": 0, ...},
                ...
              ]
            },
            ...
          ]
        },
        ...
      ]
    """
    if isinstance(start_date, datetime):
        current_dt = start_date
    else:
        # 만약 start_date가 string 이라면 변환이 필요
        # 여기서는 datetime 객체라고 가정
        current_dt = datetime(start_date.year, start_date.month, start_date.day)

    if isinstance(end_date, datetime):
        end_dt = end_date
    else:
        end_dt = datetime(end_date.year, end_date.month, end_date.day)

    # 최종적으로 return할 리스트
    all_data = []

    while current_dt <= end_dt:
        # YYYY-MM-DD 형태
        date_str = current_dt.strftime('%Y-%m-%d')

        # (1) 하루치 판매량 API 호출
        result_data = get_hourly_sales(option_codes, date_str)

        # (2) 파싱 & 해당 일자의 totalUnits 합산
        daily_total_units = 0
        detail_list = []   # 상세 구조를 저장할 리스트 (optionCode별 등)
        
        if result_data and isinstance(result_data, dict):
            content_list = result_data.get('content', [])
            for content_item in content_list:
                option_code = content_item.get('optionCode', '')
                hourly_sales_list = content_item.get('hourlySalesData', [])

                # 시간대별로 totalUnits 합계
                sub_total_units = 0
                for row in hourly_sales_list:
                    sub_total_units += row.get('totalUnits', 0)

                daily_total_units += sub_total_units

                # detail_list에 저장 (필요 없으면 생략 가능)
                detail_list.append({
                    "optionCode": option_code,
                    "hourlySalesData": hourly_sales_list,
                    "option_daily_units": sub_total_units
                })

        # (3) 오늘 일자 정보를 all_data에 append
        all_data.append({
            "date": date_str,
            "daily_total_units": daily_total_units,
            "detail": detail_list
        })

        # (4) 다음 날짜로 이동 (하루씩 증가)
        current_dt += timedelta(days=1)

    return all_data