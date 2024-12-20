# return_process/utils.py

from .models import ReturnItem
from datetime import datetime
from dateutil.parser import parse
import logging
from .api_clients import (
    NAVER_ACCOUNTS,
    COUPANG_ACCOUNTS,
    fetch_naver_returns,
    fetch_coupang_returns,
    fetch_coupang_exchanges,
    get_order_detail,
    get_external_vendor_sku,
    get_return_request_details,
)
from .maps import receipt_type_map, receipt_status_map, cancel_reason_category_map, status_code_mapping


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
            logger.info("네이버 API로부터 받은 원본 데이터(JSON):")
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
        coupang_returns = fetch_coupang_returns(account)
        logger.info(f"{account['names'][0]}에서 가져온 쿠팡 반품 데이터 수: {len(coupang_returns)}")

        for return_data in coupang_returns:
            order_id = return_data.get('orderId')
            store_name = account['names'][0]
            recipient_name = return_data.get('requesterName')
            product_name = return_data.get('returnItems', [{}])[0].get('vendorItemName')
            option_name = product_name
            quantity = return_data.get('returnItems', [{}])[0].get('purchaseCount', 1)

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

            seller_product_id = return_data.get('returnItems', [{}])[0].get('sellerProductId')
            vendor_item_id = return_data.get('returnItems', [{}])[0].get('vendorItemId')

            external_vendor_sku = get_external_vendor_sku(seller_product_id, vendor_item_id, account)
            option_code = external_vendor_sku

            invoice_number, delivered_date = get_order_detail(order_id, account)

            if delivered_date and delivered_date.strip():
                try:
                    delivered_date = parse(delivered_date)
                    if timezone.is_naive(delivered_date):
                        delivered_date = timezone.make_aware(delivered_date, timezone.get_current_timezone())
                except Exception as e:
                    logger.error(f"Delivered date parsing error: {e}")
                    delivered_date = None
            else:
                delivered_date = None

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

            existing_item = ReturnItem.objects.filter(platform='Coupang', order_number=order_id).first()
            if existing_item and existing_item.collect_tracking_number:
                continue

            ReturnItem.objects.update_or_create(
                platform='Coupang',
                order_number=order_id,
                defaults={
                    'claim_type': claim_type_kor,
                    'store_name': store_name,
                    'recipient_name': recipient_name,
                    'option_code': option_code,
                    'product_name': product_name,
                    'option_name': option_name,
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

        # 쿠팡 교환 데이터 처리
        exchanges = fetch_coupang_exchanges(account)
        logger.info(f"{account['names'][0]}에서 가져온 쿠팡 교환 데이터 수: {len(exchanges)}")

        for exchange_data in exchanges:
            order_id = exchange_data.get('orderId')
            store_name = account['names'][0]
            recipient_name = exchange_data.get('requesterName')
            product_name = exchange_data.get('exchangeItemDtoV1s', [{}])[0].get('vendorItemName')
            option_name = product_name
            quantity = exchange_data.get('exchangeItemDtoV1s', [{}])[0].get('purchaseCount', 1)

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

            seller_product_id = exchange_data.get('exchangeItemDtoV1s', [{}])[0].get('sellerProductId')
            vendor_item_id = exchange_data.get('exchangeItemDtoV1s', [{}])[0].get('vendorItemId')

            external_vendor_sku = get_external_vendor_sku(seller_product_id, vendor_item_id, account)
            option_code = external_vendor_sku

            invoice_number, delivered_date = get_order_detail(order_id, account)
            if delivered_date and delivered_date.strip():
                try:
                    delivered_date = parse(delivered_date)
                    if timezone.is_naive(delivered_date):
                        delivered_date = timezone.make_aware(delivered_date, timezone.get_current_timezone())
                except Exception as e:
                    logger.error(f"Delivered date parsing error: {e}")
                    delivered_date = None
            else:
                delivered_date = None

            collect_tracking_number = ''
            collect_delivery_company = ''

            existing_item = ReturnItem.objects.filter(platform='Coupang', order_number=order_id).first()
            if existing_item and existing_item.collect_tracking_number:
                continue

            ReturnItem.objects.update_or_create(
                platform='Coupang',
                order_number=order_id,
                defaults={
                    'claim_type': claim_type_kor,
                    'store_name': store_name,
                    'recipient_name': recipient_name,
                    'option_code': option_code,
                    'product_name': product_name,
                    'option_name': option_name,
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