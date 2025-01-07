import requests
import time
import hmac
import hashlib
import json
from urllib.parse import quote
from decouple import config
import logging


logger = logging.getLogger(__name__)


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
    logger.debug(f"=== DEBUG: [get_inventory] response data={data}")

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