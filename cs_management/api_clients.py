import requests
import time
import hmac
import hashlib
import json
from urllib.parse import quote
from decouple import config
import logging
from datetime import datetime, timedelta, timezone
import base64
import bcrypt
import urllib.parse
from urllib.parse import urlencode
from .models import Inquiry,CoupangOrderSheet
import openai
import os
from dateutil import parser
from .models import CenterInquiry
import pytz



logger = logging.getLogger(__name__)


ST_API_KEY = config('ST_API_KEY', default=None)
ST_SECRET_KEY = config('ST_SECRET_KEY', default=None)
openai.api_key = config('OPENAI_API_KEY', default=None)

REQUEST_URL_INVENTORY = 'https://sellertool-api-server-function.azurewebsites.net/api/inventories/search/stocks-by-optionCodes'
REQUEST_URL_OPTION_BY_CODE = 'https://sellertool-api-server-function.azurewebsites.net/api/product-options/search/by-optionCodes'
REQUEST_URL_OPTIONS = 'https://sellertool-api-server-function.azurewebsites.net/api/product-options'


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
        'wing_id':'pcysammai',
    },
    {
        'names': ['A00800631','쿠팡02'],
        'access_key': config('COUPANG_ACCESS_KEY_02', default=None),
        'secret_key': config('COUPANG_SECRET_KEY_02', default=None),
        'vendor_id': config('COUPANG_VENDOR_ID_02', default=None),
        'wing_id':'piaar21',
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
    response = requests.post(url, data=params)
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


def fetch_naver_qna_templates(
    from_date=None,   
    to_date=None,     
    answered=None,    
    page=1,
    size=50
):
    """
    네이버 모든 계정(NAVER_ACCOUNTS)에 대해 '상품 문의(QnA)'를 가져오고,
    결과를 합쳐서 하나의 리스트로 반환.
    
    - fromDate, toDate, answered=true/false, page, size 등 파라미터 사용
    - 반환: (True, merged_data) or (False, "에러메시지")
      merged_data = {"contents":[...], "partial_errors":"..."} (필요 시)
    """
    # 1) 날짜 기본 설정
    if not from_date or not to_date:
        kst = timezone(timedelta(hours=9))
        end_dt = datetime.now(tz=kst)
        start_dt = end_dt - timedelta(days=14)
        if not from_date:
            from_date = start_dt.isoformat(timespec='milliseconds')
        if not to_date:
            to_date = end_dt.isoformat(timespec='milliseconds')

    # 파라미터 공통 (초기 page/size 세팅은 크게 중요치 않음)
    params = {
        "fromDate": from_date,
        "toDate": to_date,
        "page": page,
        "size": size
    }
    if answered is not None:
        params["answered"] = "true" if answered else "false"

    # 2) NAVER_ACCOUNTS 전체 반복
    all_contents = []
    partial_fail_msgs = []

    for acc_info in NAVER_ACCOUNTS:
        acc_name = acc_info['names'][0] if acc_info.get('names') else "NAVER"
        
        # (A) 액세스 토큰 발급
        access_token = fetch_naver_access_token(acc_info)
        if not access_token:
            msg = f"{acc_name}: 토큰 발급 실패!"
            logger.error(msg)
            partial_fail_msgs.append(msg)
            continue
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        # (B) 페이징 반복
        all_pages_contents = []  # 이 계정(acc_name)에 대한 모든 페이지 QnA 누적
        success_for_acc = False  # 이 계정에서 최종 성공했는지 여부

        current_page = 1
        while True:
            # 각 페이지마다 params 갱신
            params = {
                "fromDate": from_date,
                "toDate": to_date,
                "page": current_page,
                "size": size
            }
            if answered is not None:
                params["answered"] = "true" if answered else "false"

            logger.debug(f"[fetch_naver_qna_templates] GET => {acc_name}, params={params}")
            
            try:
                resp = requests.get(
                    "https://api.commerce.naver.com/external/v1/contents/qnas",
                    headers=headers,
                    params=params,
                    timeout=30
                )
                logger.debug(f"[{acc_name}] status_code={resp.status_code}")
                logger.debug(f"[{acc_name}] raw response => {resp.text[:1000]}")

                # -- 200 OK인 경우 --
                if resp.status_code == 200:
                    data = resp.json()
                    contents = data.get('contents', [])
                    total_pages = data.get('totalPages', 1)
                    
                    logger.info(
                        f"[{acc_name}] QnA 수={len(contents)}, "
                        f"total={data.get('totalElements', 0)}, "
                        f"(page={data.get('page', '-')}/{total_pages}, size={data.get('size','-')})"
                    )

                    # 계정명 추가 후 이 계정의 임시 리스트에 누적
                    for c in contents:
                        c['accountName'] = acc_name
                    all_pages_contents.extend(contents)

                    # 혹시라도 데이터가 없어서 total_pages가 0일 때를 대비(이론상은 1 이상일텐데..)
                    if total_pages < 1:
                        success_for_acc = True
                        break

                    # 현재 페이지가 마지막 페이지이면 루프 종료
                    if current_page >= total_pages:
                        success_for_acc = True
                        break
                    else:
                        current_page += 1

                # -- 429 Too Many Requests --
                elif resp.status_code == 429:
                    logger.warning(f"[{acc_name}] 429 Too Many Requests (Rate Limit). 재시도 대기...")
                    time.sleep(5)
                    continue

                # -- 그 외 에러 --
                else:
                    detail_msg = f"{acc_name} => {resp.status_code}, {resp.text}"
                    logger.error(f"[{acc_name}] QnA 조회 실패: {detail_msg}")
                    partial_fail_msgs.append(detail_msg)
                    break  # 다음 페이지로 넘어가지 않고 중단

            except requests.exceptions.RequestException as e:
                msg = f"[{acc_name}] 요청 예외: {str(e)}"
                logger.error(msg)
                partial_fail_msgs.append(msg)
                break
        
        # (C) 이 계정에서 페이지 순회가 정상 종료(success_for_acc=True)했으면
        if success_for_acc:
            # 최종 all_contents에 합치기
            all_contents.extend(all_pages_contents)
        else:
            # 페이징 중간에 에러나서 중단된 경우
            logger.warning(f"[{acc_name}] 최종 실패. partial_fail_msgs에 기록됨.")

    # 4) 모든 계정 반복 끝
    if not all_contents and partial_fail_msgs:
        # 전부 실패
        return False, f"모든 계정 실패 => {partial_fail_msgs}"

    # 부분 성공 or 전체 성공
    merged_data = {
        "contents": all_contents,
    }
    if partial_fail_msgs:
        # 일부 계정 실패
        merged_data["partial_errors"] = partial_fail_msgs
        logger.warning(f"일부 계정 실패. total_contents={len(all_contents)}")
        return True, merged_data
    else:
        # 전부 성공
        return True, merged_data

def fetch_coupang_inquiries(
    start_date=None,
    end_date=None,
    answeredType='ALL',
    pageNum=1,
    pageSize=10
):
    """
    쿠팡 모든 계정(COUPANG_ACCOUNTS)에 대해
    상품별 고객문의 조회 API를 호출하고, 결과를 합침.

    - start_date, end_date: "YYYY-MM-DD" (7일 전 ~ 오늘 등)
    - answeredType: "ALL"/"ANSWERED"/"NOANSWER"
    - pageNum, pageSize: 페이지 설정
    - 반환: (True, merged_data) / (False, "에러메시지")
      merged_data = { "contents":[...], "partial_errors":[...]}
    """


    if not start_date or not end_date:
        # 기본 7일 전 ~ 오늘

        kst = pytz.timezone("Asia/Seoul")
        now_kst = datetime.now(kst)
        if not end_date:
            end_date = now_kst.strftime('%Y-%m-%d')
        if not start_date:
            # 6일 전 => 총 7일 범위
            start_dt = now_kst - timedelta(days=6)
            start_date = start_dt.strftime('%Y-%m-%d')

    all_contents = []      # 모든 계정에서 받은 문의 총합
    partial_fails = []     # 일부 계정 실패 기록

    # (A) 모든 쿠팡 계정 루프
    for acc_info in COUPANG_ACCOUNTS:
        acc_name = acc_info['names'][0] if acc_info.get('names') else "COUPANG"
        vendor_id = acc_info.get('vendor_id')
        access_key = acc_info.get('access_key')
        secret_key = acc_info.get('secret_key')

        # 필수 키 체크
        if not (vendor_id and access_key and secret_key):
            msg = f"[{acc_name}] 쿠팡 계정정보(vendor_id/access_key/secret_key) 누락!"
            partial_fails.append(msg)
            continue

        # (B) 요청 준비
        method = "GET"
        url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/onlineInquiries"
        query_params = {
            "vendorId": vendor_id,
            "answeredType": answeredType,  # "ALL" / "ANSWERED" / "NOANSWER"
            "inquiryStartAt": start_date,  # "YYYY-MM-DD"
            "inquiryEndAt": end_date,      # "YYYY-MM-DD"
            "pageSize": pageSize,
            "pageNum": pageNum
        }

        sorted_query_params = sorted(query_params.items())
        canonical_query_string = '&'.join(
            f"{k}={urllib.parse.quote(str(v), safe='~')}"
            for k, v in sorted_query_params
        )

        signature, datetime_now = generate_coupang_signature(
            method, url_path,
            dict(sorted_query_params),
            secret_key
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

        # (C) 실제 GET 요청 (재시도 로직)
        logger.debug(f"[fetch_coupang_inquiries] {acc_name} => {endpoint}")
        MAX_RETRIES = 3
        retry_count = 0
        success_for_acc = False

        while retry_count < MAX_RETRIES:
            try:
                resp = requests.get(endpoint, headers=headers, timeout=30)
                logger.debug(f"[fetch_coupang_inquiries] {acc_name} status={resp.status_code}")
                logger.debug("[fetch_coupang_inquiries] FULL response => %s", resp.text)

                if resp.status_code == 200:
                    data = resp.json()
                    code = data.get("code")
                    if code == 200:
                        # 문의 목록 => data["data"]["content"] 등에 있음
                        contents_arr = data.get("data", {}).get("content", [])
                        logger.info(f"[{acc_name}] 쿠팡 문의 {len(contents_arr)}개 pageNum={pageNum}, pageSize={pageSize}")
                        # 각 문의에 acc_name 표시
                        for c in contents_arr:
                            c['accountName'] = acc_name
                        all_contents.extend(contents_arr)
                        success_for_acc = True
                        break
                    else:
                        msg = f"[{acc_name}] code != 200, raw={data}"
                        logger.error(msg)
                        partial_fails.append(msg)
                        break
                elif resp.status_code == 429:
                    retry_count += 1
                    logger.warning(f"[{acc_name}] RateLimit(429) => 재시도 {retry_count}/{MAX_RETRIES}")
                    time.sleep(5)
                    continue
                else:
                    msg = f"[{acc_name}] status={resp.status_code}, text={resp.text}"
                    logger.error(msg)
                    partial_fails.append(msg)
                    break
            except requests.exceptions.RequestException as e:
                msg = f"[{acc_name}] 예외: {str(e)}"
                logger.error(msg)
                partial_fails.append(msg)
                break

        if not success_for_acc:
            logger.warning(f"[{acc_name}] 최종 실패 => partial_fails에 기록")

    # (D) 모든 계정 반복 끝
    if not all_contents and partial_fails:
        # 전부 실패
        return False, f"모든 쿠팡 계정 실패 => {partial_fails}"

    # 부분 성공 or 전체 성공
    merged_data = {"contents": all_contents}
    if partial_fails:
        merged_data["partial_errors"] = partial_fails
        logger.warning(f"[fetch_coupang_inquiries] 부분실패 => total={len(all_contents)}")
        return True, merged_data
    else:
        logger.info(f"[fetch_coupang_inquiries] 전부 성공 => total={len(all_contents)}")
        return True, merged_data


def fetch_coupang_order_sheet_save(account_info, order_id):
    """
    쿠팡 발주서 단건 조회 API 호출 -> 받은 data를 CoupangOrderSheet 모델에 그대로 저장
    """


    method = "GET"
    vendor_id = account_info.get("vendor_id")
    access_key = account_info.get("access_key")
    secret_key = account_info.get("secret_key")

    if not (vendor_id and access_key and secret_key):
        msg = "계정 정보(vendor_id, access_key, secret_key) 누락!"
        logger.error(msg)
        return False, msg

    url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/{order_id}/ordersheets"
    datetime_now = time.strftime('%y%m%dT%H%M%SZ', time.gmtime())
    query_params = {}

    canonical_query_string = '&'.join(
        f"{k}={urllib.parse.quote(str(v), safe='~')}" for k, v in sorted(query_params.items())
    )
    message = datetime_now + method + url_path + canonical_query_string
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    endpoint = "https://api-gateway.coupang.com" + url_path
    if canonical_query_string:
        endpoint += f"?{canonical_query_string}"

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        ),
    }

    try:
        resp = requests.get(endpoint, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                result_list = data.get("data", [])
                if not result_list:
                    logger.warning(f"[fetch_coupang_order_sheet_save] no data for orderId={order_id}")
                    return True, []
                
                saved_objs = []
                for item in result_list:
                    shipment_box_id = item.get("shipmentBoxId")
                    order_id_val = item.get("orderId")

                    def parse_dt_naive_to_aware(dt_str):
                        """
                        쿠팡 응답(예: 2025-01-20T12:11:15) → naive -> aware
                        """
                        if dt_str:
                            try:
                                dt_naive = parser.parse(dt_str)  # e.g. 2025-01-20 12:11:15
                                # localize (settings.TIME_ZONE), or Asia/Seoul if KST
                                dt_aware = timezone.make_aware(dt_naive, timezone.get_default_timezone())
                                return dt_aware
                            except ValueError:
                                pass
                        return None

                    ordered_at_dt = parse_dt_naive_to_aware(item.get("orderedAt"))
                    paid_at_dt = parse_dt_naive_to_aware(item.get("paidAt"))
                    in_transit_dt = parse_dt_naive_to_aware(item.get("inTrasitDateTime"))
                    delivered_dt = parse_dt_naive_to_aware(item.get("deliveredDate"))

                    receiver = item.get("receiver", {})
                    receiver_name = receiver.get("name")
                    receiver_safe = receiver.get("safeNumber")
                    receiver_addr1 = receiver.get("addr1")
                    receiver_addr2 = receiver.get("addr2")
                    receiver_postcode = receiver.get("postCode")

                    orderer = item.get("orderer", {})
                    orderer_name = orderer.get("name")
                    orderer_safenum = orderer.get("safeNumber")

                    order_items = item.get("orderItems", [])

                    obj, created = CoupangOrderSheet.objects.update_or_create(
                        shipment_box_id=shipment_box_id,
                        defaults={
                            "order_id": order_id_val,
                            "ordered_at": ordered_at_dt,
                            "paid_at": paid_at_dt,
                            "status": item.get("status"),
                            "shipping_price": item.get("shippingPrice", 0),
                            "remote_price": item.get("remotePrice", 0),
                            "remote_area": item.get("remoteArea", False),
                            "parcel_print_message": item.get("parcelPrintMessage", ""),
                            "split_shipping": item.get("splitShipping", False),
                            "able_split_shipping": item.get("ableSplitShipping", False),
                            "orderer_name": orderer_name,
                            "orderer_safenum": orderer_safenum,
                            "receiver_name": receiver_name,
                            "receiver_safenum": receiver_safe,
                            "receiver_addr1": receiver_addr1,
                            "receiver_addr2": receiver_addr2,
                            "receiver_postcode": receiver_postcode,
                            "delivery_company_name": item.get("deliveryCompanyName"),
                            "invoice_number": item.get("invoiceNumber"),
                            "in_transit_datetime": in_transit_dt,
                            "delivered_date": delivered_dt,
                            "refer": item.get("refer"),
                            "shipment_type": item.get("shipmentType"),
                            "order_items": order_items,

                            # 그대로 저장
                            "raw_json": item,
                        }
                    )
                    saved_objs.append(obj)
                
                logger.info(f"[fetch_coupang_order_sheet_save] saved {len(saved_objs)} boxes for orderId={order_id}")
                return True, saved_objs
            else:
                msg = f"API code != 200, raw={data}"
                logger.error(msg)
                return False, msg
        else:
            detail_msg = f"status={resp.status_code}, text={resp.text}"
            logger.error(f"[fetch_coupang_order_sheet_save] {detail_msg}")
            return False, detail_msg

    except requests.exceptions.RequestException as e:
        msg = f"[fetch_coupang_order_sheet_save] 요청 예외: {str(e)}"
        logger.error(msg)
        return False, msg


def save_naver_inquiries_to_db(data):
    """
    네이버 '상품 문의(QnA)' 통합 데이터(모든 계정) => Inquiry 모델에 저장
    (item에 c['accountName']로 어느 계정문의인지 식별)
    """
    contents = data.get("contents", [])
    saved_list = []

    for item in contents:
        inquiry_id = item.get("questionId")
        product_id = item.get("productId")
        product_name = item.get("productName")
        question_str = item.get("question")
        masked_writer = item.get("maskedWriterId")
        answered_bool = item.get("answered", False)
        answer_str = item.get("answer")
        create_date_str = item.get("createDate")
        account_name = item.get("accountName", "NAVER")  # <--- ★

  
        created_dt = None
        if create_date_str:
            try:
                dt = parser.parse(create_date_str)
                created_dt = dt.astimezone(timezone.utc)
            except:
                pass

        obj, created = Inquiry.objects.update_or_create(
            platform="NAVER",
            inquiry_id=inquiry_id,
            defaults={
                "product_id": product_id,
                "product_name": product_name,
                "content": question_str,
                "author": masked_writer,
                "created_at_utc": created_dt,
                "answered": answered_bool,
                "answer_content": answer_str,
                # store_name = account_name
                "store_name": account_name,
                "raw_json": item,
            }
        )
        saved_list.append(obj)

    logger.info(f"[save_naver_inquiries_to_db] saved/updated {len(saved_list)} inquiries.")
    return saved_list
# ---------------------------
# (B) 쿠팡 문의 DB 저장
# ---------------------------



def save_coupang_inquiries_to_db(merged_data):
    """
    쿠팡 문의 데이터를 Inquiry 모델에 저장.
    - sellerProductId로 displayProductName 조회 후, product_name 업데이트.

    :param merged_data: {"contents": [{..., "accountName": "A00291106"}, ...]}
    """


    contents = merged_data.get("contents", [])
    saved_objs = []

    for item in contents:
        inquiry_id = item.get("inquiryId")
        seller_product_id = item.get("sellerProductId")
        acc_name = item.get("accountName", "")  # 예: "A00291106", "쿠팡01"
        if not inquiry_id:
            continue

        # (1) account_info 찾기
        account_info = next(
            (acc for acc in COUPANG_ACCOUNTS if any(acc_name in n for n in acc['names'])),
            None
        )

        # (2) 기본 정보 파싱
        answered_bool = bool(item.get("commentDtoList", []))
        inquiry_at_str = item.get("inquiryAt")  # "2025-01-29 23:32:57"
        created_dt = parser.parse(inquiry_at_str).astimezone(timezone.utc) if inquiry_at_str else None

        # (3) 상품명 조회 (sellerProductId 기반)
        product_name = ""
        if seller_product_id and account_info:
            success, product_data = fetch_coupang_seller_product(account_info, seller_product_id)
            if success:
                product_name = product_data.get("displayProductName", "")

        # (4) DB 저장
        obj, created = Inquiry.objects.update_or_create(
            platform="COUPANG",
            inquiry_id=inquiry_id,
            defaults={
                "store_name": acc_name,
                "product_id": item.get("productId"),
                "seller_product_id": seller_product_id,
                "product_name": product_name,
                "content": item.get("content", ""),
                "author": item.get("buyerEmail", ""),
                "answered": answered_bool,
                "created_at_utc": created_dt,
                "raw_json": item,
            }
        )
        saved_objs.append(obj)

    return saved_objs


def put_naver_qna_answer(account_info, question_id, comment_content):
    """
    네이버 '상품 문의 답변' 등록/수정 API.
    PUT /external/v1/contents/qnas/{questionId}
    
    ...
    """
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        msg = f"{account_info['names'][0]} 토큰 발급 실패"
        logger.error(msg)
        return False, msg

    base_url = "https://api.commerce.naver.com"
    endpoint = f"/external/v1/contents/qnas/{question_id}"

    url = base_url + endpoint
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Content-Type': "application/json"
    }

    payload = {
        "commentContent": comment_content
    }

    MAX_RETRIES = 3
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            resp = requests.put(url, headers=headers, json=payload, timeout=30)
            logger.debug(f"[put_naver_qna_answer] status_code={resp.status_code}, resp={resp.text[:200]}")

            if resp.status_code in [200, 204]:
                # 네이버가 204로 응답할 수도 있음 -> 둘 다 성공 처리
                data = {}
                if resp.status_code == 200 and resp.text:
                    # 200이고 응답 바디가 있으면 JSON 파싱
                    data = resp.json()
                
                logger.info(
                    f"[{account_info['names'][0]}] 문의답변 등록/수정 성공 (status={resp.status_code}), questionId={question_id}"
                )
                return True, data

            elif resp.status_code == 429:
                # Rate Limit
                retry_count += 1
                logger.warning(f"[put_naver_qna_answer] 429, 재시도 {retry_count}")
                time.sleep(5)
                continue

            else:
                # 나머지는 실패
                msg = f"status={resp.status_code}, text={resp.text}"
                logger.error(f"[put_naver_qna_answer] 실패: {msg}")
                return False, msg

        except requests.exceptions.RequestException as e:
            msg = f"[put_naver_qna_answer] 요청 예외: {str(e)}"
            logger.error(msg)
            return False, msg

    msg = "[put_naver_qna_answer] 재시도 초과"
    logger.error(msg)
    return False, msg


def fetch_coupang_seller_product(account_info, seller_product_id):
    """
    등록상품ID(sellerProductId)로 쿠팡 상품 정보를 조회
    => data["data"]["displayProductName"] 등을 얻을 수 있음
    
    :param account_info: 쿠팡 API 계정( access_key, secret_key, vendor_id )
    :param seller_product_id: 등록상품ID
    :return: (True, product_info_dict) or (False, "오류메시지")
    """


    access_key = account_info.get("access_key")
    secret_key = account_info.get("secret_key")
    vendor_id = account_info.get("vendor_id")

    if not (access_key and secret_key and vendor_id):
        msg = f"[fetch_coupang_seller_product] 계정정보 누락!"
        logger.error(msg)
        return False, msg

    method = "GET"
    url_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
    query_params = {}  # 없음

    # 시그니처 생성
    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)

    host = "https://api-gateway.coupang.com"
    endpoint = f"{host}{url_path}"

    # 헤더
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        ),
    }

    MAX_RETRIES = 3
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            resp = requests.get(endpoint, headers=headers, timeout=30)
            logger.debug(f"[fetch_coupang_seller_product] status={resp.status_code}, text={resp.text[:500]}")

            if resp.status_code == 200:
                data = resp.json()
                # 보통 { "code":"SUCCESS", "message":"OK", "data":{...} } 구조
                if data.get("code") == "SUCCESS":
                    product_info = data.get("data", {})
                    return True, product_info
                else:
                    msg = f"code != SUCCESS, raw={data}"
                    logger.error(msg)
                    return False, msg

            elif resp.status_code == 429:
                logger.warning("[fetch_coupang_seller_product] 429 -> 재시도")
                retry_count += 1
                time.sleep(5)
                continue

            else:
                msg = f"status={resp.status_code}, text={resp.text}"
                logger.error(msg)
                return False, msg

        except requests.exceptions.RequestException as e:
            msg = f"[fetch_coupang_seller_product] 예외: {str(e)}"
            logger.error(msg)
            return False, msg

    return False, "[fetch_coupang_seller_product] 재시도 초과"


def put_coupang_inquiry_answer(account_info, inquiry_id, content, reply_by=None):

    vendor_id = account_info.get('vendor_id')
    access_key = account_info.get('access_key')
    secret_key = account_info.get('secret_key')

    if not (vendor_id and access_key and secret_key):
        msg = "[put_coupang_inquiry_answer] 계정정보 부족"
        logger.error(msg)
        return False, msg

    # reply_by가 None라면, account_info['vendor_id'] 사용(백업)
    if not reply_by:
        reply_by = account_info.get('wing_id')

    logger.debug(f"[put_coupang_inquiry_answer] inquiry_id={inquiry_id}, content={content[:30]}, reply_by={reply_by}, vendor_id={vendor_id}")

    method = "POST"
    url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/onlineInquiries/{inquiry_id}/replies"
    query_params = {}

    signature, datetime_now = generate_coupang_signature(method, url_path, query_params, secret_key)

    host = "https://api-gateway.coupang.com"
    endpoint = f"{host}{url_path}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={datetime_now}, signature={signature}"
        ),
    }

    payload = {
        "content": content,
        "vendorId": vendor_id,
        "replyBy": reply_by
    }

    MAX_RETRIES = 3
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
            logger.debug(f"[put_coupang_inquiry_answer] status={resp.status_code}, text={resp.text}")

            if resp.status_code == 200:
                data = resp.json()
                code_val = data.get("code")  # e.g. 200 (int)
                # 1) 정수 비교
                if code_val == 200:
                    return True, data
                else:
                    msg = f"code != 200, raw={data}"
                    logger.error(msg)
                    return False, msg

            elif resp.status_code == 429:
                logger.warning("[put_coupang_inquiry_answer] 429 RateLimit => 재시도")
                retry_count += 1
                time.sleep(5)
                continue
            else:
                msg = f"status={resp.status_code}, text={resp.text}"
                logger.error(f"[put_coupang_inquiry_answer] 실패: {msg}")
                return False, msg

        except requests.exceptions.RequestException as e:
            logger.error(f"[put_coupang_inquiry_answer] 예외: {str(e)}")
            return False, str(e)

    return False, "[put_coupang_inquiry_answer] 재시도 초과"



def fetch_gpt_recommendation(inquiry_text, max_tokens=200):
    """
    inquiry_text: 사용자가 남긴 문의(요약, 내용, etc.)를 기반으로
    GPT에게 '추천 답변'을 생성해 달라고 요청하는 예시.

    returns: GPT의 텍스트(답변) or 오류 메세지
    """

    if not openai.api_key:
        return False, "OPENAI_API_KEY가 없습니다."

    try:
        # (A) chatGPT 방식을 사용할 수도 있고 (gpt-3.5-turbo),
        #     text completion 방식을 사용할 수도 있습니다.
        # 여기서는 chatGPT 예시:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  
            messages=[
                {"role": "system", "content": "당신은 친절한 고객 상담원입니다."},
                {"role": "user", "content": f"문의 내용:\n{inquiry_text}\n\n위 문의에 대한 적절한 답변을 생성해줘."}
            ],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        # (B) 응답 파싱
        choice = response["choices"][0]["message"]["content"]
        return True, choice.strip()
    except openai.error.OpenAIError as e:
        return False, f"GPT API 오류: {str(e)}"
    



#고객센터문의 시작
def fetch_naver_center_inquiries(
    start_date=None,  # YYYY-MM-DD
    end_date=None,    # YYYY-MM-DD
    answered=None,    # True->"true", False->"false", None->all
    page=1,
    size=50
):
    """
    네이버 “플랫폼센터 문의” API:
      GET /v1/pay-user/inquiries
    (multi-account 방식)
    
    파라미터:
      start_date, end_date (둘 다 필수, 없으면 기본 7일 전 ~ 오늘)
      answered -> "true"/"false"
      page, size => 초기 요청용 (페이지네이션)
    
    반환:
      (True, {"contents":[{...}, ...], "partial_errors":[...optional...]})
      (False, "에러메시지")
    """

    # 1) 날짜 디폴트
    if not start_date or not end_date:

        kst = timezone.get_default_timezone()  # 예: Asia/Seoul
        now_kst = datetime.now(kst)
        if not end_date:
            end_date = now_kst.strftime('%Y-%m-%d')
        if not start_date:
            start_dt = now_kst - timedelta(days=7)
            start_date = start_dt.strftime('%Y-%m-%d')

    # 2) 쿼리 파라미터(기본)
    base_params = {
        "startSearchDate": start_date,  # yyyy-MM-dd
        "endSearchDate": end_date,
        "page": page,
        "size": size
    }
    if answered is not None:
        base_params["answered"] = "true" if answered else "false"

    all_contents = []
    partial_errors = []

    # (A) 모든 NAVER 계정 루프
    for acc_info in NAVER_ACCOUNTS:
        acc_name = acc_info['names'][0] if acc_info.get('names') else "NAVER_Center"
        
        # (A1) 토큰
        token = fetch_naver_access_token(acc_info)
        if not token:
            msg = f"{acc_name} => 토큰 발급 실패!"
            partial_errors.append(msg)
            continue
        
        headers = {
            "Authorization": f"Bearer {token}"
        }
        # (A2) 페이징
        current_page = page
        success_for_acc = False
        account_all_contents = []
        while True:
            params = dict(base_params)
            params["page"] = current_page  # 현재 페이지
            try:
                url = "https://api.commerce.naver.com/external/v1/pay-user/inquiries"
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    # totalPages, page, size, content[], ...
                    content_arr = data.get("content", [])
                    total_pages = data.get("totalPages", 1)
                    # 각 item에 accountName 추가
                    for c in content_arr:
                        c["accountName"] = acc_name
                    account_all_contents.extend(content_arr)
                    if current_page >= total_pages:
                        success_for_acc = True
                        break
                    else:
                        current_page += 1
                elif resp.status_code == 429:
                    import time
                    time.sleep(5)
                    continue
                else:
                    msg = f"[{acc_name}] status={resp.status_code}, text={resp.text}"
                    partial_errors.append(msg)
                    break
            except requests.exceptions.RequestException as e:
                partial_errors.append(f"[{acc_name}] 요청 예외: {str(e)}")
                break
        
        if success_for_acc:
            all_contents.extend(account_all_contents)
        else:
            pass  # 일부 실패 기록됨

    if not all_contents and partial_errors:
        # 전부 실패
        return (False, f"[fetch_naver_center_inquiries] 모든 계정 실패 => {partial_errors}")
    merged_data = {
        "contents": all_contents
    }
    if partial_errors:
        merged_data["partial_errors"] = partial_errors
    return (True, merged_data)


def fetch_coupang_center_inquiries(
    start_date=None, # yyyy-MM-dd
    end_date=None,   # yyyy-MM-dd
    partnerCounselingStatus="NONE", # NONE=전체, NO_ANSWER=미답변, ANSWER=답변완료, TRANSFER=미확인
    pageNum=1,
    pageSize=10
):
    """
    쿠팡 “고객센터 문의” API:
      GET /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries
    
    파라미터:
      start_date, end_date -> inquiryStartAt, inquiryEndAt (없으면 최대 7일)
      partnerCounselingStatus -> NONE/NO_ANSWER/ANSWER/TRANSFER
      pageNum, pageSize
    
    반환:
      (True, {"contents":[...], "partial_errors":[...]})
      (False, "에러메시지")
    """

    

    # 1) 날짜 기본
    if not start_date or not end_date:

        now_kst = timezone.now()
        if not end_date:
            end_date = now_kst.strftime('%Y-%m-%d')
        if not start_date:
            start_dt = now_kst - timedelta(days=6)
            start_date = start_dt.strftime('%Y-%m-%d')

    all_contents = []
    partial_errors = []

    # (A) 모든 쿠팡 계정
    for acc_info in COUPANG_ACCOUNTS:
        acc_name = acc_info['names'][0] if acc_info.get('names') else "COUPANG_Center"
        vendor_id = acc_info.get('vendor_id')
        access_key = acc_info.get('access_key')
        secret_key = acc_info.get('secret_key')

        if not (vendor_id and access_key and secret_key):
            msg = f"[{acc_name}] 계정정보 부족(vendor_id/access_key/secret_key)"
            partial_errors.append(msg)
            continue
        
        # base params
        base_params = {
            "vendorId": vendor_id,
            "partnerCounselingStatus": partnerCounselingStatus,  # "NONE"/"NO_ANSWER"/"ANSWER"/"TRANSFER"
            "inquiryStartAt": start_date,
            "inquiryEndAt": end_date,
            "pageNum": pageNum,
            "pageSize": pageSize
        }

        method = "GET"
        url_path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/callCenterInquiries"
        import urllib
        sorted_q = sorted(base_params.items())
        query_str = '&'.join(f"{k}={urllib.parse.quote(str(v), safe='~')}" for k,v in sorted_q)
        signature, datetime_now = generate_coupang_signature(method, url_path, dict(sorted_q), secret_key)

        endpoint = f"https://api-gateway.coupang.com{url_path}"
        if query_str:
            endpoint += f"?{query_str}"
        
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": (
                f"CEA algorithm=HmacSHA256, access-key={access_key}, "
                f"signed-date={datetime_now}, signature={signature}"
            ),
        }

        MAX_RETRIES = 3
        retry_count = 0
        success_for_acc = False

        while retry_count < MAX_RETRIES:
            try:
                resp = requests.get(endpoint, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    code_val = data.get("code") # ex: 200
                    if code_val == 200:
                        content_arr = data.get("data", {}).get("content", [])
                        # ex: data["data"]["pagination"] = { currentPage, totalPages, ...}
                        pagination = data.get("data", {}).get("pagination", {})
                        total_pages = pagination.get("totalPages", 1)
                        # each item => add accountName
                        for c in content_arr:
                            c["accountName"] = acc_name
                        all_contents.extend(content_arr)
                        success_for_acc = True
                        break
                    else:
                        msg = f"[{acc_name}] code != 200 => raw={data}"
                        partial_errors.append(msg)
                        break
                elif resp.status_code == 429:
                    retry_count += 1
                    time.sleep(5)
                    continue
                else:
                    msg = f"[{acc_name}] status={resp.status_code}, text={resp.text}"
                    partial_errors.append(msg)
                    break
            except requests.exceptions.RequestException as e:
                partial_errors.append(f"[{acc_name}] 예외: {str(e)}")
                break
        
        if not success_for_acc:
            pass  # 실패 기록
    
    if not all_contents and partial_errors:
        return (False, f"모든 쿠팡계정 실패 => {partial_errors}")
    
    merged = {"contents": all_contents}
    if partial_errors:
        merged["partial_errors"] = partial_errors
    return (True, merged)


def save_center_naver_inquiries_to_db(data):
    """
    네이버 '고객센터 문의' 데이터를 CenterInquiry 모델에 저장/업데이트.
    :param data: {"contents": [ {...}, {...}, ... ]}
    """
    contents = data.get("contents", [])
    saved_list = []

    for item in contents:
        # 1) 각 필드 값 추출
        inquiry_id = item.get("inquiryNo")  # 문의 식별자
        if not inquiry_id:
            continue
        
        inquiry_title = item.get("title")  # 문의 제목
        inquiry_content = item.get("inquiryContent")  # 문의 내용
        category = item.get("category")  # 문의 유형/카테고리
        answered = item.get("answered", False)  # 답변 여부
        answer_content = item.get("answerContent")  # 답변 내용
        orderId01 = item.get("orderId")  # 주문번호
        product_id = item.get("productNo")  # 상품번호
        product_name = item.get("productName")  # 상품명
        option_name = item.get("productOrderOption")  # 옵션정보
        author = item.get("customerId")  # 구매자ID
        customer_name = item.get("customerName")  # 구매자 정보
        store_name = item.get("accountName", "NAVER")  # 스토어명
        # 주문번호(배열) => 네이버는 productOrderIdList가 배열일 수 있으므로 문자열 변환 예시:
        orderId02_list = item.get("productOrderIdList", [])
        orderId02_str = ",".join([str(x) for x in orderId02_list]) if isinstance(orderId02_list, list) else str(orderId02_list)

        # 2) 날짜 필드 파싱
        created_at_utc = None
        created_at_str = item.get("inquiryRegistrationDateTime")  # ISO8601
        if created_at_str:
            try:
                dt = parser.parse(created_at_str)
                created_at_utc = dt.astimezone(timezone.utc)
            except:
                created_at_utc = None

        answer_date = None
        answer_date_str = item.get("answerRegistrationDateTime")
        if answer_date_str:
            try:
                dt = parser.parse(answer_date_str)
                answer_date = dt.astimezone(timezone.utc)
            except:
                answer_date = None

        # 아직 네이버 API에는 별도 'ordered_at'(주문일자) 제공이 없다고 가정
        ordered_at = None

        # 3) DB 저장/업데이트
        obj, created = CenterInquiry.objects.update_or_create(
            platform="NAVER",
            inquiry_id=inquiry_id,
            defaults={
                "inquiry_title": inquiry_title,
                "inquiry_content": inquiry_content,
                "created_at_utc": created_at_utc,
                "category": category,
                "answered": answered,
                "answer_content": answer_content,
                "orderId01": orderId01,
                "product_id": product_id,
                "product_name": product_name,
                "option_name": option_name,
                "author": author,
                "customer_name": customer_name,
                "store_name": store_name,
                "orderId02": orderId02_str,
                "answer_date": answer_date,
                "ordered_at": ordered_at,
                # 나머지 필드 (answered_at, answer_updated_at 등)은 현재 값이 없으므로 None
                "answered_at": None,
                "answer_updated_at": None,
                # 아직 대표이미지, gpt_* 등은 미정
                "representative_image": None,
                "gpt_summary": None,
                "gpt_recommendation_1": None,
                "gpt_recommendation_2": None,
                "gpt_confidence_score": None,
                "gpt_used_answer_index": None,
            }
        )
        saved_list.append(obj)

    return saved_list



def save_center_coupang_inquiries_to_db(data):
    """
    쿠팡 '고객센터 문의' 데이터를 CenterInquiry 모델에 저장/업데이트.
    :param data: {"contents": [ {...}, {...}, ... ]}
    """
    contents = data.get("contents", [])
    saved_list = []

    for item in contents:
        # 1) 쿠팡 문의 식별자
        inquiry_id = item.get("inquiryId")
        if not inquiry_id:
            continue

        # 2) 필드 파싱
        # 제목이 없으므로 itemName이 있으면 그걸 사용, 없으면 receiptCategory 사용
        item_name = item.get("itemName")  # "상품명 / 옵션명" 형태를 가정
        receipt_category = item.get("receiptCategory", "")
        inquiry_title = ""

        # --- inquiry_content: replies에 있는 내용 우선 ---
        replies = item.get("replies") or []
        if replies:
            # replies가 있으면, 여러 개 reply의 content를 모두 합치기
            inquiry_content = "\n\n-----\n\n".join(r.get("content", "") for r in replies)
        else:
            # replies가 없으면, 원래 item["content"]를 사용
            inquiry_content = item.get("content")  # 문의 내용

        category = item.get("receiptCategory", "")
        
        # --- 답변 여부 & 내용 ---
        cs_status = item.get("csPartnerCounselingStatus", "").upper()  # 예: "COMPLETE", "INCOMPLETE"
        answered = (cs_status == "COMPLETE") or (len(replies) > 0)
        
        # 답변 내용: replies[0]["content"] (여러 개면 추가로 처리)
        answer_content = None
        answer_date = None
        if replies:
            answer_content = replies[0].get("content")
            # 답변일자
            answer_date_str = replies[0].get("replyAt")
            if answer_date_str:
                try:
                    dt = parser.parse(answer_date_str)
                    answer_date = dt.astimezone(timezone.utc)
                except:
                    answer_date = None

        # --- 날짜 파싱 ---
        created_at_utc = None
        inquiry_at_str = item.get("inquiryAt")  # "2025-01-29 11:24:00"
        if inquiry_at_str:
            try:
                dt = parser.parse(inquiry_at_str)
                created_at_utc = dt.astimezone(timezone.utc)
            except:
                created_at_utc = None
        
        ordered_at = None
        order_date_str = item.get("orderDate")  # 주문일자
        if order_date_str:
            try:
                dt = parser.parse(order_date_str)
                ordered_at = dt.astimezone(timezone.utc)
            except:
                ordered_at = None

        # --- 기타 ---
        orderId01 = str(item.get("orderId", ""))     # 주문번호
        product_id = str(item.get("vendorItemId", ""))  # 상품번호
        # itemName에 "상품명 / 옵션명" 형식이 있다고 가정하면:
        # product_name = 앞쪽, option_name = 뒷쪽?
        product_name = ""
        option_name = ""
        if item_name and " / " in item_name:
            splitted = item_name.split(" / ", 1)
            product_name = splitted[0]
            option_name = splitted[1] if len(splitted) > 1 else ""
        else:
            # itemName 구조가 달라질 경우 fallback
            product_name = item_name
            option_name = ""

        # "상품주문번호" => orderId02 = vendorItemId 그대로 사용 가능
        orderId02 = product_id

        author = str(item.get("orderId", ""))  # 구매자ID => "orderid로 받아와야함" 가정
        customer_name = str(item.get("orderId", ""))  # 실제 API에 구매자명/닉네임이 없어서 동일 처리
        store_name = item.get("accountName", "쿠팡")   # 스토어명

        # 3) DB 저장/업데이트
        obj, created = CenterInquiry.objects.update_or_create(
            platform="COUPANG",
            inquiry_id=inquiry_id,
            defaults={
                "inquiry_title": inquiry_title,
                "inquiry_content": inquiry_content,
                "created_at_utc": created_at_utc,
                "category": category,
                "answered": answered,
                "answer_content": answer_content,
                "orderId01": orderId01,
                "product_id": product_id,
                "product_name": product_name,
                "option_name": option_name,
                "author": author,
                "customer_name": customer_name,
                "store_name": store_name,
                "orderId02": orderId02,
                "answer_date": answer_date,
                "ordered_at": ordered_at,
                "answered_at": None,  # 아직 별도 필드가 없으므로 None
                "answer_updated_at": None,
                "representative_image": None,  # 미정
                "gpt_summary": None,
                "gpt_recommendation_1": None,
                "gpt_recommendation_2": None,
                "gpt_confidence_score": None,
                "gpt_used_answer_index": None,
            }
        )
        saved_list.append(obj)

    return saved_list


def post_naver_center_inquiry_answer(account_info, inquiry_no, answer_comment, answer_template_id=None):
    """
    네이버 '고객센터 문의'에 답변을 등록하는 API 호출 함수.
    POST /v1/pay-merchant/inquiries/{inquiryNo}/answer

    :param account_info: dict - 네이버 계정 정보 (ex: {"names": ["네이버스토어1"], ...})
    :param inquiry_no: int - 문의 번호
    :param answer_comment: str - 답변 내용
    :param answer_template_id: str or None - (선택) 답변 템플릿 ID
    :return: (success, data or msg)
        - success=True, data=dict => 성공
        - success=False, msg=str   => 실패 메시지
    """
    # 1) 액세스 토큰
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        msg = f"{account_info['names'][0]} 토큰 발급 실패"
        logger.error(msg)
        return False, msg

    # 2) 요청 URL & 헤더
    base_url = "https://api.commerce.naver.com"
    endpoint = f"/v1/pay-merchant/inquiries/{inquiry_no}/answer"
    url = base_url + endpoint

    headers = {
        'Authorization': f"Bearer {access_token}",
        'Content-Type': "application/json"
    }

    # 3) 요청 바디
    payload = {
        "answerComment": answer_comment
        # answerTemplateId가 있으면 추가
    }
    if answer_template_id:
        payload["answerTemplateId"] = answer_template_id

    MAX_RETRIES = 3
    retry_count = 0

    while retry_count < MAX_RETRIES:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            logger.debug(f"[post_naver_center_inquiry_answer] status_code={resp.status_code}, resp={resp.text[:300]}")

            if resp.status_code == 200:
                # 성공 => resp.json() 파싱
                data = {}
                try:
                    data = resp.json()
                except Exception:
                    pass

                logger.info(
                    f"[{account_info['names'][0]}] 문의답변 등록 성공 (status=200), inquiry_no={inquiry_no}"
                )
                return True, data

            elif resp.status_code == 429:
                # Rate Limit 초과 => 재시도
                retry_count += 1
                logger.warning(f"[post_naver_center_inquiry_answer] 429: Too Many Requests, 재시도 {retry_count}")
                time.sleep(5)
                continue

            else:
                # 그 외 => 실패
                msg = f"status={resp.status_code}, text={resp.text}"
                logger.error(f"[post_naver_center_inquiry_answer] 실패: {msg}")
                return False, msg

        except requests.exceptions.RequestException as e:
            msg = f"[post_naver_center_inquiry_answer] 요청 예외: {str(e)}"
            logger.error(msg)
            return False, msg

    msg = "[post_naver_center_inquiry_answer] 재시도 초과"
    logger.error(msg)
    return False, msg


def put_naver_qna_center_answer(account_info, inquiry_no, answer_comment):
    """
    네이버 '고객센터 문의' 답변 등록 API (CenterInquiry).
    POST /v1/pay-merchant/inquiries/{inquiryNo}/answer

    :param account_info: dict - 네이버 스토어 계정 정보 (토큰 발급용)
    :param inquiry_no: int - 네이버 고객센터 문의 번호
    :param answer_comment: str - 등록할 답변 내용
    :return: (success: bool, data_or_msg)
        - success=True이면 성공, data_or_msg는 응답 JSON (dict)
        - success=False이면 실패, data_or_msg는 실패 원인(str)
    """

    # 1) 액세스 토큰 발급
    access_token = fetch_naver_access_token(account_info)
    if not access_token:
        msg = f"{account_info['names'][0]} 토큰 발급 실패"
        logger.error(msg)
        return False, msg

    # 2) 엔드포인트
    base_url = "https://api.commerce.naver.com"
    endpoint = f"/v1/pay-merchant/inquiries/{inquiry_no}/answer"
    url = base_url + endpoint

    headers = {
        'Authorization': f"Bearer {access_token}",
        'Content-Type': "application/json"
    }

    # 3) 요청 바디
    payload = {
        "answerComment": answer_comment
    }

    # (A) 디버그용 로그: 함수 진입 시 어떤 값들을 가지고 있는지 확인
    logger.debug(
        f"[put_naver_qna_center_answer] 준비: store={account_info['names'][0]}, "
        f"inquiry_no={inquiry_no}, answer_comment={answer_comment}"
    )
    logger.debug(f"[put_naver_qna_center_answer] url={url}, payload={payload}")

    # 4) 재시도 로직
    MAX_RETRIES = 3
    retry_count = 0

    while retry_count < MAX_RETRIES:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            # (B) 요청 후 응답 코드와 일부 본문 로깅
            logger.debug(f"[put_naver_qna_center_answer] status_code={resp.status_code}, resp={resp.text[:300]}")

            if resp.status_code == 200:
                # 성공 -> 응답 JSON 파싱
                data = {}
                try:
                    data = resp.json()
                except Exception:
                    pass  # 응답 바디가 없거나 JSON 파싱 실패 시 빈 dict
                logger.info(
                    f"[{account_info['names'][0]}] 고객센터 문의 답변 등록 성공 (status=200), inquiry_no={inquiry_no}"
                )
                return True, data

            elif resp.status_code == 429:
                # Rate Limit -> 재시도
                retry_count += 1
                logger.warning(f"[put_naver_qna_center_answer] 429(Too Many Requests), 재시도 {retry_count}")
                time.sleep(5)
                continue

            else:
                # 그 외 상태코드는 실패 처리
                msg = f"status={resp.status_code}, text={resp.text}"
                logger.error(f"[put_naver_qna_center_answer] 실패: {msg}")
                return False, msg

        except requests.exceptions.RequestException as e:
            msg = f"[put_naver_qna_center_answer] 요청 예외: {str(e)}"
            logger.error(msg)
            return False, msg

    # 5) 재시도 초과
    msg = "[put_naver_qna_center_answer] 재시도 초과"
    logger.error(msg)
    return False, msg