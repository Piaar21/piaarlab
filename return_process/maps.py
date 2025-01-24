receipt_type_map = {
    'RETURN': '반품',
    'CANCEL_REQUEST': '취소 요청',
    'RETURN_REQUEST': '반품 요청',
    'EXCHANGE_REQUEST': '교환 요청',
    'COMPENSATION_REQUEST': '보상 요청',
}

receipt_status_map = {
    'CANCEL_REQUEST': '취소 요청',
    'CANCEL_ACCEPT': '취소 수락',
    'CANCEL_REJECT': '취소 거부',
    'RETURNS_COMPLETED': '반품 완료',
    'RELEASE_STOP_UNCHECKED': '출고중지요청',
    'RETURNS_UNCHECKED': '반품접수',
    'VENDOR_WAREHOUSE_CONFIRM': '입고완료',
    'REQUEST_COUPANG_CHECK': '쿠팡확인요청',
    'RETURN_REQUEST': '반품 요청',
    'RETURN_ACCEPT': '반품 수락',
    'RETURN_REJECT': '반품 거부',
    'RETURN_COMPLETE': '반품 완료',
    'EXCHANGE_REQUEST': '교환 요청',
    'EXCHANGE_ACCEPT': '교환 수락',
    'EXCHANGE_REJECT': '교환 거부',
    'COLLECTING'	: '수거중',
    'COLLECT_DONE'    : '수거완료',
    'EXCHANGE_DONE	': '교환완료',
    'RETURN_REJECT	': '반품철회',
    'EXCHANGE_REJECT': '교환철회',
}

cancel_reason_category_map = {
    'CUSTOMER_CHANGE': '고객변심',
    'SELLER_FAULTY': '판매자 귀책',
    'DROPPED_DELIVERY': '배송 중 분실',
    'DAMAGED_DELIVERY': '배송 중 파손',
    'WRONG_DELIVERY': '오배송',  # 이미 여기에도 '오배송'이 있으나 상황에 따라 사용
    'PRODUCT_UNSATISFIED': '상품 불만족',
    'PRODUCT_DEFECT': '상품 불량',
}

status_code_mapping = {
    'WRONG_DELIVERED_PRODUCT': '오배송',
    'WRONG_PRODUCT_CONTENT': '상품 내용 불일치',
    'WRONG_DELAYED_DELIVERY': '배송 지연',
    'SIMPLE_INTENT_CHANGED': '단순 변심',
    'MISTAKE_ORDER': '주문 실수',
    'NO_LONGER_NEED_PRODUCT': '상품이 필요 없음',
    'PRODUCT_UNSATISFIED': '상품에 만족하지 않음',
    'PRODUCT_UNSATISFIED_COLOR': '색상 불만족',
    'PRODUCT_UNSATISFIED_SIZE': '사이즈 불만족',
    'BROKEN_AND_BAD': '상품 불량 및 파손',
    'PRODUCT_UNSATISFIED_ETC': '기타 불만족',
    'RETURN_REQUEST': '반품 요청',
    'RETURN_REJECT': '반품 철회',
    'RETURN_COMPLETED': '반품 완료',
    'EXCHANGE_REQUEST': '교환 요청',
    'EXCHANGE_REJECT': '교환 철회',
    'EXCHANGE_COMPLETED': '교환 완료',
    'COLLECT_WAITING': '회수 대기 중',
    'COLLECT_DONE': '회수 완료',
    'COLLECT_DELAYED': '회수 지연',
    'DELIVERED': '배송 완료',
    'DELIVERY_COMPLETION': '배송 완료',
    'DELIVERING': '배송 중',
    'SHIPPING': '배송 준비 중',
    'RETURN_DONE': '반품 완료',
    'PURCHASE_DECIDED': '구매 확정',

    # 추가한 매핑
    'COLOR_AND_SIZE': '색상 및 사이즈 변경',
    'WRONG_DELIVERY': '오배송',
}

product_order_status_map = {
    'PAYMENT_WAITING': '결제 대기',
    'PAYED': '결제 완료',
    'DELIVERING': '배송 중',
    'DELIVERED': '배송 완료',
    'PURCHASE_DECIDED': '구매 확정',
    'EXCHANGED': '교환완료',
    'CANCELED': '취소완료',
    'RETURNED': '반품완료',
    'CANCELED_BY_NOPAYMENT': '미결제 취소'
}