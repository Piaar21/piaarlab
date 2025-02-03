# 예: cs_management/utils.py (또는 views.py 등 편한 위치)

from delayed_management.models import OutOfStock
from cs_management.models import Inquiry
from django.db.models import Q
import requests
import logging


logger = logging.getLogger(__name__)

def fill_inquiry_images_from_outofstock():
    """
    (1) Inquiry 중 representative_image가 비어있는 레코드 탐색
    (2) 동일 product_id를 가진 OutOfStock에서 representative_image가 있는지 확인
    (3) 있으면 Inquiry.representative_image에 복사
    """
    # 1) 대표이미지 비어있는 Inquiry (네이버, 쿠팡 등 어느 platform이든 가능)
    qs = Inquiry.objects.filter(
        Q(representative_image__isnull=True) | Q(representative_image__exact='')
    ).exclude(product_id__isnull=True).exclude(product_id__exact='')

    print(f"[fill_inquiry_images_from_outofstock] 대상 Inquiry count={qs.count()}")

    for inq in qs:
        pid = inq.product_id

        # 2) OutOfStock에서 동일 product_id 가진 레코드 중, representative_image가 있는지
        out_item = OutOfStock.objects.filter(
            product_id=pid,
            representative_image__isnull=False
        ).exclude(representative_image__exact='').first()

        if out_item:
            # 3) Inquiry 대표이미지 채우기
            inq.representative_image = out_item.representative_image
            inq.save()
            print(f"[fill_inquiry_images_from_outofstock] Inquiry(id={inq.inquiry_id}) => 이미지={out_item.representative_image}")
        else:
            print(f"[fill_inquiry_images_from_outofstock] product_id={pid}, OutOfStock에 이미지 없음")


DOORAY_WEBHOOK_URL = "https://piaar.dooray.com/services/3206627054248384796/3992197902174434125/fdT_mAoTTDe0V_1q-Kmetg"

def send_inquiry_to_dooray_webhook(store_name: str, product_name: str, content: str) -> bool:
    """
    Dooray 웹훅에 문의 정보를 POST로 전송하는 예시 함수.
    
    - store_name : 스토어명
    - product_name : 상품명
    - content : 문의내용
    """
    # 웹훅으로 넘길 데이터 (Dooray의 경우, 단순 텍스트도 가능)
    # 자유롭게 JSON 포맷 구성하시면 됩니다.
    payload = {
        "botName": "문의알림봇",      # Dooray에서 표시될 봇 이름 (선택)
        "botIconImage": "",         # 아이콘 URL (선택)
        # attachments 없이 단순 text만 전송해도 됩니다.
        "text": f"상품 담당자는 아래 문의에 대한 답변을 달아주세요!\n\n"
                f"스토어명: {store_name}\n"
                f"상품명: {product_name}\n"
                f"문의내용: {content}\n"
    }

    try:
        resp = requests.post(DOORAY_WEBHOOK_URL, json=payload, timeout=5)
        logger.debug(f"[send_inquiry_to_dooray_webhook] status={resp.status_code}, text={resp.text}")
        if resp.status_code == 200:
            return True
        else:
            logger.error(f"Dooray Webhook 실패: {resp.status_code}, {resp.text}")
            return False
    except requests.RequestException as e:
        logger.exception(f"Dooray Webhook 전송 중 예외 발생: {e}")