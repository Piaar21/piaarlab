# return_process/utils.py

from .models import ReturnItem
from datetime import datetime
from dateutil.parser import parse
import logging
from django.utils import timezone
from .maps import receipt_type_map, receipt_status_map, cancel_reason_category_map, status_code_mapping
from .models import ReturnItem, NaverAccount, CoupangAccount

from .api_clients import (
    NAVER_ACCOUNTS,
    COUPANG_ACCOUNTS,
    fetch_naver_returns,
    fetch_coupang_returns,
    fetch_coupang_exchanges,
    get_seller_product_item_id,
    get_order_detail,
    get_external_vendor_sku,
    get_return_request_details,
    approve_naver_return,
    get_product_order_details,
)
import json





logger = logging.getLogger(__name__)


def save_return_items(data, platform):
    for item in data:
        logger.info(f"저장하는 아이템: {item}")
        ReturnItem.objects.update_or_create(
            order_id=item['orderId'],  # 주문번호
            defaults={
                'product_name': item.get('productName', ''),
                'customer_name': item.get('customerName', ''),
                'status': item.get('status', ''),
                'requested_date': datetime.strptime(item['requestedDate'], '%Y-%m-%dT%H:%M:%S'),
                'platform': platform,
                # 추가로 저장하고 싶은 필드를 여기에 추가
            }
        )

def update_returns_logic():
    logger.info("update_returns_logic 호출됨")
    
    # 네이버 반품 및 교환 데이터 업데이트
    logger.info(f"네이버 계정 수: {len(NAVER_ACCOUNTS)}")
    for account in NAVER_ACCOUNTS:
        logger.info(f"Processing Naver account: {account['names'][0]}")
        naver_returns = fetch_naver_returns(account)
        logger.info(f"{account['names'][0]}에서 가져온 네이버 반품/교환 데이터 수: {len(naver_returns)}")

        if not naver_returns:
            logger.info(f"{account['names'][0]}에서 가져온 데이터가 없습니다.")
            continue

        for return_data in naver_returns:
            # logger.info("네이버 API로부터 받은 원본 데이터(JSON):")
            logger.info(json.dumps(return_data, ensure_ascii=False, indent=4))

            product_order = return_data.get('productOrder', {})
            delivery = return_data.get('delivery', {})

            order_number = product_order.get('productOrderId')
            if not order_number:
                logger.error("order_number가 없습니다. 데이터를 건너뜁니다.")
                continue

            # claimType에 따라 처리 로직 분기
            claim_type = product_order.get('claimType')
            claim_type_kor = status_code_mapping.get(claim_type, claim_type)

            if claim_type == 'RETURN':
                claim_data = return_data.get('return', {})
                claim_reason = claim_data.get('returnReason', "N/A")
                customer_reason = claim_data.get('returnDetailedReason', '')
                collect_tracking_number = claim_data.get('collectTrackingNumber', '')
                collect_delivery_company = claim_data.get('collectDeliveryCompany', '')
            elif claim_type == 'EXCHANGE':
                claim_data = return_data.get('exchange', {})
                claim_reason = claim_data.get('exchangeReason', "N/A")
                customer_reason = claim_data.get('exchangeDetailedReason', '')
                collect_tracking_number = claim_data.get('collectTrackingNumber', '')
                collect_delivery_company = claim_data.get('collectDeliveryCompany', '')
            else:
                claim_data = {}
                claim_reason = "N/A"
                customer_reason = ""
                collect_tracking_number = ""
                collect_delivery_company = ""

            store_name = account['names'][0]
            recipient_name = product_order.get('shippingAddress', {}).get('name')
            recipient_contact = product_order.get('shippingAddress', {}).get('tel1', '')
            option_code = product_order.get('optionManageCode')
            product_name = product_order.get('productName')
            option_name = product_order.get('productOption')

            quantity = claim_data.get('requestQuantity', 1)
            invoice_number = delivery.get('trackingNumber', '')
            claim_status = claim_data.get('claimStatus')
            claim_status_kor = status_code_mapping.get(claim_status, claim_status if claim_status else "N/A")

            return_shipping_charge = claim_data.get('claimDeliveryFeeDemandAmount')
            shipping_charge_payment_method = claim_data.get('claimDeliveryFeePayMethod')

            claim_request_date_str = claim_data.get('claimRequestDate')
            if claim_request_date_str:
                try:
                    claim_request_date = parse(claim_request_date_str)
                except Exception as e:
                    logger.error(f"claim_request_date 변환 중 오류 발생 (주문번호: {order_number}): {e}")
                    claim_request_date = None
            else:
                claim_request_date = None

            delivered_date_str = delivery.get('deliveredDate')
            if delivered_date_str:
                try:
                    delivered_date = parse(delivered_date_str)
                except Exception as e:
                    logger.error(f"delivered_date 변환 중 오류 발생 (주문번호: {order_number}): {e}")
                    delivered_date = None
            else:
                delivered_date = None

            existing_item = ReturnItem.objects.filter(platform='Naver', order_number=order_number).first()
            if existing_item and existing_item.collect_tracking_number:
                logger.info(f"주문번호 {order_number}는 이미 collect_tracking_number가 존재하여 업데이트 생략")
                continue

            claim_reason_kor = status_code_mapping.get(claim_reason, claim_reason)
            customer_reason_kor = status_code_mapping.get(customer_reason, customer_reason)

            logger.info("ReturnItem update_or_create 호출 전 필드 값:")
            logger.info(f"platform='Naver', order_number={order_number}, claim_status={claim_status_kor}")

            try:
                ReturnItem.objects.update_or_create(
                    platform='Naver',
                    order_number=order_number,
                    defaults={
                        'claim_type': claim_type_kor,
                        'store_name': store_name,
                        'recipient_name': recipient_name,
                        'recipient_contact': recipient_contact,
                        'option_code': option_code,
                        'product_name': product_name,
                        'option_name': option_name,
                        'quantity': quantity,
                        'invoice_number': invoice_number,
                        'claim_status': claim_status_kor,
                        'claim_reason': claim_reason_kor,
                        'customer_reason': customer_reason_kor,
                        'return_shipping_charge': return_shipping_charge,
                        'shipping_charge_payment_method': shipping_charge_payment_method,
                        'collect_tracking_number': collect_tracking_number,
                        'collect_delivery_company': collect_delivery_company,
                        'claim_request_date': claim_request_date,
                        'delivered_date': delivered_date,
                    }
                )
                logger.info(f"ReturnItem 저장 또는 업데이트 성공: {order_number}")
            except Exception as e:
                logger.error(f"ReturnItem 저장 중 오류 발생 (주문번호: {order_number}): {e}")
                logger.error("오류 발생 시 return_data 전체:")
                logger.error(json.dumps(return_data, ensure_ascii=False, indent=4))
                continue

    logger.info(f"쿠팡 계정 수: {len(COUPANG_ACCOUNTS)}")

    # 쿠팡 반품 및 교환 데이터 업데이트
    for account in COUPANG_ACCOUNTS:
        logger.info(f"Processing Coupang account: {account['names'][0]}")
        
        # -----------------------------
        # (1) 쿠팡 반품
        # -----------------------------
        coupang_returns = fetch_coupang_returns(account)
        logger.info(f"{account['names'][0]}에서 가져온 쿠팡 반품 데이터 수: {len(coupang_returns)}")

        for return_data in coupang_returns:
            order_id = return_data.get('orderId')
            store_name = account['names'][0]
            recipient_name = return_data.get('requesterName')
            
            # 공통 필드(반품 전체에 해당) 추출
            claim_type = return_data.get('receiptType')
            claim_type_kor = receipt_type_map.get(claim_type, claim_type)

            claim_status = return_data.get('receiptStatus')
            claim_status_kor = receipt_status_map.get(claim_status, claim_status)

            claim_reason = return_data.get('cancelReasonCategory1')
            claim_reason_kor = cancel_reason_category_map.get(claim_reason, claim_reason)

            customer_reason = return_data.get('cancelReasonCategory2')
            customer_reason_kor = cancel_reason_category_map.get(customer_reason, customer_reason)

            return_shipping_charge = return_data.get('returnShippingCharge')
            claim_request_date_str = return_data.get('createdAt')

            if claim_request_date_str:
                claim_request_date = parse(claim_request_date_str)
                if timezone.is_naive(claim_request_date):
                    claim_request_date = timezone.make_aware(claim_request_date, timezone.get_current_timezone())
            else:
                claim_request_date = None
            
            # (A) returnItems가 여러 개 있을 수 있으므로 루프
            return_items = return_data.get('returnItems', [])
            if not return_items:
                # 만약 returnItems가 비어 있다면 건너뜀
                continue

            # (B) 배송일/운송장번호 조회 (주문 단위로 한 번만 호출)
            invoice_number, delivered_date = get_order_detail(order_id, account)
            if delivered_date and delivered_date.strip():
                try:
                    delivered_date_parsed = parse(delivered_date)
                    if timezone.is_naive(delivered_date_parsed):
                        delivered_date_parsed = timezone.make_aware(delivered_date_parsed, timezone.get_current_timezone())
                    delivered_date = delivered_date_parsed
                except Exception as e:
                    logger.error(f"Delivered date parsing error: {e}")
                    delivered_date = None
            else:
                delivered_date = None
            
            # (C) 회수 송장번호/배송사 (receiptId 기준)
            return_request_details = get_return_request_details(account['vendor_id'], return_data.get('receiptId'), account)
            collect_tracking_number = ''
            collect_delivery_company = ''
            if return_request_details:
                data_item = return_request_details.get('data', {})
                if data_item:
                    return_delivery_dtos = data_item.get('returnDeliveryDtos', [])
                    if return_delivery_dtos:
                        for dto in return_delivery_dtos:
                            collect_tracking_number = dto.get('deliveryInvoiceNo', '')
                            collect_delivery_company = dto.get('deliveryCompanyCode', '')
                            break
            
            # (D) 아이템별로 DB 저장
            for item in return_items:
                product_name = item.get('vendorItemName')
                quantity = item.get('purchaseCount', 1)
                seller_product_id = item.get('sellerProductId')
                vendor_item_id = item.get('vendorItemId')
                
                # external SKU 매핑
                external_vendor_sku = get_external_vendor_sku(seller_product_id, vendor_item_id, account)
                option_code = external_vendor_sku

                # ★ order_number = orderId - vendorItemId
                order_number = f"{order_id}-{vendor_item_id}"

                # 혹시 기존에 이미 collect_tracking_number가 채워져 있다면 건너뛰기
                existing_item = ReturnItem.objects.filter(platform='Coupang', order_number=order_number).first()
                if existing_item and existing_item.collect_tracking_number:
                    continue

                ReturnItem.objects.update_or_create(
                    platform='Coupang',
                    order_number=order_number,
                    defaults={
                        'claim_type': claim_type_kor,
                        'store_name': store_name,
                        'recipient_name': recipient_name,
                        'option_code': option_code,
                        'product_name': product_name,
                        'option_name': product_name,  # 기존 코드에서는 option_name = product_name
                        'quantity': quantity,
                        'invoice_number': invoice_number,
                        'claim_status': claim_status_kor,
                        'claim_reason': claim_reason_kor,
                        'customer_reason': customer_reason_kor,
                        'return_shipping_charge': return_shipping_charge,
                        'collect_tracking_number': collect_tracking_number,
                        'collect_delivery_company': collect_delivery_company,
                        'claim_request_date': claim_request_date,
                        'delivered_date': delivered_date,
                    }
                )
        
        # -----------------------------
        # (2) 쿠팡 교환
        # -----------------------------
        exchanges = fetch_coupang_exchanges(account)
        logger.info(f"{account['names'][0]}에서 가져온 쿠팡 교환 데이터 수: {len(exchanges)}")

        for exchange_data in exchanges:
            order_id = exchange_data.get('orderId')
            store_name = account['names'][0]
            recipient_name = exchange_data.get('requesterName')

            # 공통 필드(교환 전체에 해당)
            claim_type = exchange_data.get('receiptType')
            claim_type_kor = receipt_type_map.get(claim_type, claim_type)

            claim_status = exchange_data.get('exchangeStatus')
            claim_status_kor = receipt_status_map.get(claim_status, claim_status)

            claim_reason = exchange_data.get('reasonCode')
            claim_reason_kor = cancel_reason_category_map.get(claim_reason, claim_reason)

            customer_reason = exchange_data.get('reasonCodeText', '')
            return_shipping_charge = exchange_data.get('returnShippingCharge')
            claim_request_date_str = exchange_data.get('createdAt')

            if claim_request_date_str:
                claim_request_date = parse(claim_request_date_str)
                if timezone.is_naive(claim_request_date):
                    claim_request_date = timezone.make_aware(claim_request_date, timezone.get_current_timezone())
            else:
                claim_request_date = None

            # (A) 교환 아이템 배열
            exchange_items = exchange_data.get('exchangeItemDtoV1s', [])
            if not exchange_items:
                continue
            
            # (B) 배송일/운송장 조회
            invoice_number, delivered_date = get_order_detail(order_id, account)
            if delivered_date and delivered_date.strip():
                try:
                    delivered_date_parsed = parse(delivered_date)
                    if timezone.is_naive(delivered_date_parsed):
                        delivered_date_parsed = timezone.make_aware(delivered_date_parsed, timezone.get_current_timezone())
                    delivered_date = delivered_date_parsed
                except Exception as e:
                    logger.error(f"Delivered date parsing error: {e}")
                    delivered_date = None
            else:
                delivered_date = None
            
            # 교환에는 수거(collect) 정보가 현재 로직상 없거나, 필요하면 로직 추가
            collect_tracking_number = ''
            collect_delivery_company = ''

            # (C) 아이템별로 DB 저장
            for item in exchange_items:
                product_name = item.get('vendorItemName')
                quantity = item.get('purchaseCount', 1)
                seller_product_id = item.get('sellerProductId')
                vendor_item_id = item.get('vendorItemId')

                # external SKU 매핑
                external_vendor_sku = get_external_vendor_sku(seller_product_id, vendor_item_id, account)
                option_code = external_vendor_sku

                # ★ order_number = orderId - vendorItemId
                order_number = f"{order_id}-{vendor_item_id}"

                existing_item = ReturnItem.objects.filter(platform='Coupang', order_number=order_number).first()
                if existing_item and existing_item.collect_tracking_number:
                    continue

                ReturnItem.objects.update_or_create(
                    platform='Coupang',
                    order_number=order_number,
                    defaults={
                        'claim_type': claim_type_kor,
                        'store_name': store_name,
                        'recipient_name': recipient_name,
                        'option_code': option_code,
                        'product_name': product_name,
                        'option_name': product_name,
                        'quantity': quantity,
                        'invoice_number': invoice_number,
                        'claim_status': claim_status_kor,
                        'claim_reason': claim_reason_kor,
                        'customer_reason': customer_reason,
                        'return_shipping_charge': return_shipping_charge,
                        'collect_tracking_number': collect_tracking_number,
                        'collect_delivery_company': collect_delivery_company,
                        'claim_request_date': claim_request_date,
                        'delivered_date': delivered_date,
                    }
                )

    logger.info("반품 데이터 업데이트 로직 완료")


    
import time
import hmac
import hashlib
from typing import Dict, Any

def generate_sellertool_signature(api_key: str, secret_key: str) -> (str, str):
    """
    셀러툴에서 요구하는 시그니처 생성:
     - x-sellertool-timestamp: 밀리초 단위 Unix time (string)
     - x-sellertool-signiture: HmacSHA256(apiKey + timestamp, secretKey) -> hex
    """
    timestamp = str(int(time.time() * 1000))  # 밀리초 Unix Time
    message = api_key + timestamp
    signature = hmac.new(
        secret_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return timestamp, signature


def get_return_exchange_type(claim_type: str) -> str:
    """
    ReturnItem.claim_type -> 셀러툴 returnExchangeType
      '반품'   -> 'RETURN'
      '교환'   -> 'EXCHANGE'
      'RETURN' -> 'RETURN'
      'EXCHANGE' -> 'EXCHANGE'
      'N/A'    -> 'N/A'
      그 외는 기본값
    """
    mapping = {
        "반품": "RETURN",
        "교환": "EXCHANGE",
        "RETURN": "RETURN",
        "EXCHANGE": "EXCHANGE",
        "N/A": "N/A"
    }
    
    # mapping에 없는 값은 기본값으로 RETURN을 반환
    return mapping.get(claim_type, "RETURN")


def get_return_exchange_proceed_type(processing_status: str) -> str:
    """
    ReturnItem.processing_status -> 셀러툴 returnExchangeProceedStatus
    """
    mapping = {
        '미처리': 'PREPARING',
        '스캔': 'COLLECTION_REQUEST',
        '수거완료': 'COLLECTION_COMPLETE',
        '검수완료': 'INSPECTION_COMPLETE',
        '반품완료': 'RETURN_SHIPMENT',
        '재고반영': 'PROCESSING_COMPLETE',
        '처리완료': 'PROCESSING_COMPLETE',
    }
    return mapping.get(processing_status, 'PREPARING')

STORE_ID_MAP = {
    "니뜰리히": "e2fa1155-8e54-48ae-be4c-cfc77bef19d9",
    "수비다": "928c3a99-7acf-4869-bb07-cdeb6c7588ad",
    "노는개최고양": "0877c607-3849-4a6d-902e-4bb29306351d",
    "아르빙": "c483aaf6-7a82-4b51-9ece-11222a80eb1a",
    "쿠팡01": "7e915702-42f9-402c-934e-02f2257e0038",
    "쿠팡02": "9347b814-7096-4902-9353-763197988e64"
    # 필요 시 추가
}


from django.utils import timezone

def convert_return_item_to_formdata(return_item) -> dict:
    store_name = return_item.store_name or ""
    store_id = STORE_ID_MAP.get(store_name, "")
    return {
        "orderNumber1": return_item.order_number,
        "returnExchangeType": get_return_exchange_type(return_item.claim_type),
        "returnExchangeProceedStatus": get_return_exchange_proceed_type(return_item.processing_status),
        "returnExchangeQuantity": return_item.quantity or 1,
        "returnExchangeDeliveryPaidMethod": return_item.shipping_charge_payment_method or "",
        "customerRequestCollectionMethod": "",
        "collectionWaybillNumber": return_item.collect_tracking_number or "",
        "collectionOptionCode": return_item.option_code or "",
        "inspectionResultMemo": return_item.product_issue or "",
        "inspectionPassedQuantity": 0,
        "salesChannelMatchingStoreId": store_id,
        "salesChannelMatchingStoreMemo": store_name,
        "claimSystem": return_item.claim_reason or return_item.note or "",
        "claimCustomer": return_item.customer_reason or "",
        "returnExchangeMemo1": return_item.note or "",
        "returnExchangeMemo2": (
            f"검수완료시간 : {timezone.localtime(return_item.inspected_at).strftime('%Y-%m-%d %H:%M:%S')}"
            if return_item.inspected_at else ""
        )
    }
