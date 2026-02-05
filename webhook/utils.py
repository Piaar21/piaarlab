# webhook/utils.py
import os
import time
import hashlib
import hmac
import requests
import json
from decouple import config
# 환경 변수에서 API 키를 가져옵니다.
SELLERTOOL_API_KEY = config('ST_API_KEY', default=None)
SELLERTOOL_SECRET_KEY = config('ST_SECRET_KEY', default=None)



def generate_signature(api_key, secret_key, timestamp):
    """
    셀러툴(SellerTool) API 호출 시 필요한 시그니처를 생성합니다.
    시그니처는 (api_key + timestamp) 문자열을 secret_key로 HMAC-SHA256 해싱한 후, hex 형태로 표현한 값입니다.
    """
    if not api_key or not secret_key:
        raise ValueError("API 키 또는 시크릿 키가 설정되지 않았습니다.")
    
    message = api_key + timestamp
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature

def get_product_options(product_name):
    """
    셀러툴 'product-options' API를 호출하여, 특정 product_name에 대한 옵션 정보를 받아옵니다.
    :return: 옵션 정보(딕셔너리 리스트) 또는 None
    """
    REQUEST_URL_OPTIONS = 'https://shared-api.sellertool.io/api/product-options'

    # 현재 시각(밀리초) 기준으로 timestamp 생성
    timestamp = str(int(time.time() * 1000))

    # 시그니처 생성
    signature = generate_signature(SELLERTOOL_API_KEY, SELLERTOOL_SECRET_KEY, timestamp)

    # 요청 헤더
    headers = {
        'x-sellertool-apiKey': SELLERTOOL_API_KEY,
        'x-sellertool-timestamp': timestamp,
        'x-sellertool-signiture': signature
    }

    # GET 파라미터
    params = {
        'productName': product_name
    }

    try:
        response = requests.get(REQUEST_URL_OPTIONS, headers=headers, params=params)
        print(f"[get_product_options] 상태 코드: {response.status_code}")
        print(f"[get_product_options] 응답: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if 'content' in data:
                content = data['content']
                if isinstance(content, list) and len(content) > 0:
                    return content
                else:
                    print("옵션 정보가 존재하지 않습니다.")
                    return None
            else:
                print("API 응답에 'content'가 없습니다.")
                return None
        else:
            print(f"API 호출 에러: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        print(f"[get_product_options] 요청 오류: {e}")
        return None

def get_stock_by_option_codes(option_codes):
    """
    셀러툴 'inventories/search/stocks-by-optionCodes' API를 호출하여,
    여러 option_codes에 대한 재고 정보를 받아옵니다.
    :return: 재고 정보(딕셔너리 리스트) 또는 None
    """
    REQUEST_URL_STOCKS = 'https://shared-api.sellertool.io/api/inventories/search/stocks-by-optionCodes'

    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(SELLERTOOL_API_KEY, SELLERTOOL_SECRET_KEY, timestamp)

    headers = {
        'x-sellertool-apiKey': SELLERTOOL_API_KEY,
        'x-sellertool-timestamp': timestamp,
        'x-sellertool-signiture': signature
    }

    body = {
        "optionCodes": option_codes
    }

    try:
        response = requests.post(REQUEST_URL_STOCKS, json=body, headers=headers)
        print(f"[get_stock_by_option_codes] 상태 코드: {response.status_code}")
        print(f"[get_stock_by_option_codes] 응답: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if 'content' in data and isinstance(data['content'], list):
                return data['content']
            else:
                print("API 응답 형식이 다르거나 'content'가 없습니다.")
                return None
        else:
            print(f"API 호출 에러: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        print(f"[get_stock_by_option_codes] 요청 오류: {e}")
        return None

def join_data(product_options, stock_data):
    """
    상품 옵션 정보와 재고 정보를 옵션 코드 기준으로 매핑하여 병합된 리스트를 반환합니다.
    """
    joined_data = []

    # 옵션 코드(대문자) -> 옵션 정보 딕셔너리
    options_dict = {
        item['productOptionCode'].strip().upper(): item
        for item in product_options
        if 'productOptionCode' in item
    }

    for stock_item in stock_data:
        option_code = stock_item.get('code', '').strip().upper()
        if option_code and option_code in options_dict:
            merged = options_dict[option_code].copy()
            merged.update({
                '재고 수량': stock_item.get('stockUnit', 0),
                '입고 수량': stock_item.get('receiveUnit', 0),
                '출고 수량': stock_item.get('releaseUnit', 0),
            })
            joined_data.append(merged)

    return joined_data
