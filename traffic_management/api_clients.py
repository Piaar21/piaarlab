# api.py

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

    async with aiohttp.ClientSession() as session:
        tasks = []
        for start in range(1, 1001, 100):
            params = {
                'query': keyword,
                'display': 100,
                'start': start,
                'sort': 'sim',
            }
            task = asyncio.create_task(fetch(session, SEARCH_URL, headers, params, start, target_url, semaphore))
            tasks.append(task)
            await asyncio.sleep(0.1)

        responses = await asyncio.gather(*tasks)
        for result in responses:
            if result is not None:
                return result

    return -1
def get_naver_rank(keyword, target_url):
    # NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET 확인
    if not naver_client_id or not naver_client_secret:
        raise ValueError("NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET를 마이페이지에서 설정해주세요.")

    # 비동기 함수 호출
    return async_to_sync(get_naver_rank_async)(naver_client_id, naver_client_secret, keyword, target_url)