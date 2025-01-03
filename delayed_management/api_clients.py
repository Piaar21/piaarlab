import requests
import time
import hmac
import hashlib
import json
from urllib.parse import quote
from decouple import config

ST_API_KEY = config('ST_API_KEY', default=None)
ST_SECRET_KEY = config('ST_SECRET_KEY', default=None)

REQUEST_URL_INVENTORY = 'https://sellertool-api-server-function.azurewebsites.net/api/inventories/search/stocks-by-optionCodes'
REQUEST_URL_OPTION_BY_CODE = 'https://sellertool-api-server-function.azurewebsites.net/api/product-options/search/by-optionCodes'
REQUEST_URL_OPTIONS = 'https://sellertool-api-server-function.azurewebsites.net/api/product-options'

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
    headers = get_headers()
    body = {'optionCodes': option_codes}
    resp = requests.post(REQUEST_URL_INVENTORY, headers=headers, data=json.dumps(body))
    if resp.status_code == 200:
        result = resp.json()
        if result.get('content'):
            stock_map = {item['code']: item['stockUnit'] for item in result['content']}
            return stock_map
    return {}

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

def get_exchangeable_options(input_option_code, needed_qty):
    """
    주어진 옵션코드로부터 동일 상품의 교환가능 옵션을 조회 (재고 stock_unit >= needed_qty, 동일 판매가).
    * 반환 데이터 예시: [ { 'optionName': '빨강_M', 'optionCode': 'abc123' }, ... ]
    """
    # 1) 입력 옵션 코드의 기본 정보 (상품명, 판매가) 조회
    input_option_info = get_option_info_by_code(input_option_code)
    if not input_option_info or not input_option_info['productName']:
        return []  # 상품명 정보를 못 얻었으면 빈 리스트 반환

    product_name = input_option_info['productName']
    base_sales_price = input_option_info['salesPrice']

    # 2) 동일 상품명(product_name)의 모든 옵션코드 가져오기
    all_option_codes = get_all_options_by_product_name(product_name)
    if not all_option_codes:
        return []

    # 3) 옵션코드 목록의 재고/상세 정보 한꺼번에 불러오기
    inventory_map = get_inventory_by_option_codes(all_option_codes)  # { 'abc123': 재고수, ...}
    detail_map    = get_options_detail_by_codes(all_option_codes)    # { 'abc123': {'optionName':..., 'salesPrice':..., ...}, ...}

    # 4) 조건(동일 판매가 & 재고 >= needed_qty)에 맞는 항목만 골라 옵션명/코드 반환
    results = []
    for code in all_option_codes:
        detail = detail_map.get(code)
        if not detail:
            continue  # 상세 정보가 없으면 스킵

        stock_unit = inventory_map.get(code, 0)
        # 교환가능 조건:
        #  (1) 판매가가 같은지
        #  (2) 재고 stock_unit >= needed_qty
        if detail['salesPrice'] == base_sales_price and stock_unit >= needed_qty:
            results.append({
                "optionName": detail['optionName'],
                "optionCode": code
            })

    return results
