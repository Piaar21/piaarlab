from django.db import models
from django.utils import timezone


class Inquiry(models.Model):
    """
    네이버/쿠팡 문의를 한 곳에 저장하는 통합 모델 예시.
    """

    # 플랫폼 구분: 'NAVER' / 'COUPANG'
    platform = models.CharField(max_length=20)
    store_name = models.CharField(max_length=20, blank=True, null=True)
    # 문의 식별자 (네이버: id, 쿠팡: inquiryId)
    inquiry_id = models.BigIntegerField()

    # 상품 식별자 (네이버: productId, 쿠팡: productId)
    product_id = models.CharField(max_length=50,blank=True, null=True)

    # 상품명
    product_name = models.CharField(max_length=255, blank=True, null=True)

    # 문의 내용 (네이버: question, 쿠팡: content)
    content = models.TextField(blank=True, null=True)

    # 작성자(네이버 maskedWriterId, 쿠팡은 orderId로 찾은 receiver.name 등)
    author = models.CharField(max_length=100, blank=True, null=True)

    # 작성 일시(네이버 createDate, 쿠팡 inquiryAt)
    created_at_utc = models.DateTimeField(blank=True, null=True,
        help_text="문의 생성시각(UTC 변환 or local parsing)")

    # 답변 여부
    answered = models.BooleanField(default=False)

    # 추가 필드: 답변 내용, 대표이미지, 답변일시, GPT 요약
    answer_content = models.TextField(blank=True, null=True)
    representative_image = models.URLField(blank=True, null=True)
    answer_date = models.DateTimeField(blank=True, null=True)
    gpt_summary = models.TextField(blank=True, null=True)

    # 쿠팡 전용: orderIds (JSON 배열)
    order_ids = models.TextField(blank=True, null=True,
        help_text="쿠팡 문의에서 사용. e.g. '[29100091940290]'")

    # 전체 raw JSON (optional)
    raw_json = models.JSONField(blank=True, null=True)

    # Django 관리용
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    answered_at = models.DateTimeField(null=True, blank=True, help_text="최초 답변시간")
    answer_updated_at = models.DateTimeField(null=True, blank=True, help_text="답변 수정시간")

    seller_product_id = models.BigIntegerField(blank=True, null=True)  # ★ 새 필드 (쿠팡 sellerProductId)

    gpt_recommendation_1 = models.TextField(
        blank=True, null=True, 
        help_text="AI가 생성한 추천답변 #1"
    )
    gpt_recommendation_2 = models.TextField(
        blank=True, null=True, 
        help_text="AI가 생성한 추천답변 #2"
    )
    gpt_confidence_score = models.FloatField(
        blank=True, null=True, 
        help_text="GPT가 생성한 답변에 대한 신뢰도, 0~1 등"
    )
    gpt_used_answer_index = models.IntegerField(
        blank=True, null=True,
        help_text="실제 채택된 GPT 답변 인덱스(1,2 등)"
    )

    class Meta:
        # (platform, inquiry_id) 유니크로 중복 방지
        unique_together = ('platform', 'inquiry_id')
        verbose_name = "통합문의"
        verbose_name_plural = "통합문의 목록"

    
    def __str__(self):
        return f"[{self.platform}] ID={self.inquiry_id}"

    def get_answer_date_display(self):
        """
        '2025.01.29 20:02 (2025.01.29 20:04 수정)' 형태로 보여주기
        """
        if not self.answered_at:
            return ""  # 아직 답변 없음
        dt_str = self.answered_at.strftime('%Y.%m.%d %H:%M')
        if self.answer_updated_at:
            dt_str += f" ({self.answer_updated_at.strftime('%Y.%m.%d %H:%M')} 수정)"
        return dt_str




class CoupangOrderSheet(models.Model):
    """
    쿠팡 발주서 단건 조회 (ordersheets) 데이터 저장 모델.
    'data' 배열에서 각 shipmentBoxId 항목을 하나씩 저장.
    """

    # 주 식별자들
    order_id = models.BigIntegerField(help_text="orderId (주문번호)")
    shipment_box_id = models.BigIntegerField(help_text="shipmentBoxId", primary_key=True)

    # 주문일시 (orderedAt: "2024-04-08T22:54:46")
    ordered_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)

    status = models.CharField(max_length=50, blank=True, null=True)        # (e.g. FINAL_DELIVERY)
    shipping_price = models.IntegerField(blank=True, null=True)           # (0)
    remote_price = models.IntegerField(blank=True, null=True)             # (0)
    remote_area = models.BooleanField(default=False)                      # (false)
    parcel_print_message = models.CharField(max_length=255, blank=True, null=True)
    split_shipping = models.BooleanField(default=False)
    able_split_shipping = models.BooleanField(default=False)

    # 주문자(orderer) 정보 (optional)
    orderer_name = models.CharField(max_length=100, blank=True, null=True)
    orderer_safenum = models.CharField(max_length=50, blank=True, null=True)

    # 수취인(receiver) 정보
    receiver_name = models.CharField(max_length=100, blank=True, null=True)
    receiver_safenum = models.CharField(max_length=50, blank=True, null=True)
    receiver_addr1 = models.CharField(max_length=255, blank=True, null=True)
    receiver_addr2 = models.CharField(max_length=255, blank=True, null=True)
    receiver_postcode = models.CharField(max_length=20, blank=True, null=True)

    # 배송사, 운송장, 배송일시 등
    delivery_company_name = models.CharField(max_length=100, blank=True, null=True)
    invoice_number = models.CharField(max_length=100, blank=True, null=True)
    in_transit_datetime = models.DateTimeField(blank=True, null=True)
    delivered_date = models.DateTimeField(blank=True, null=True)
    refer = models.CharField(max_length=50, blank=True, null=True)         # 결제위치(안드로이드앱 등)
    shipment_type = models.CharField(max_length=50, blank=True, null=True)

    # orderItems는 여러 개 가능 => 보통 별도 테이블 or JSONField
    # 여기선 raw_json에 전부 저장 or JSONField
    # Django >= 3.1 에서 JSONField 사용 가능
    import json
    from django.contrib.postgres.fields import JSONField  # or models.JSONField (Django 3.1+)

    order_items = models.JSONField(blank=True, null=True,
        help_text="orderItems 배열 통째로 저장")

    # (추가) 대표이미지, 답변일시, GPT요약
    representative_image = models.URLField(blank=True, null=True)
    answer_date = models.DateTimeField(blank=True, null=True)
    gpt_summary = models.TextField(blank=True, null=True)

    # 전체 raw JSON (optional)
    raw_json = models.JSONField(blank=True, null=True)

    # 생성/수정 시각
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "쿠팡 발주서"
        verbose_name_plural = "쿠팡 발주서 목록"

    def __str__(self):
        return f"[CoupangOrderSheet] orderId={self.order_id}, boxId={self.shipment_box_id}"
    


class CenterInquiry(models.Model):
    inquiry_id = models.BigIntegerField(null=True, blank=True)
    inquiry_title = models.CharField(max_length=255, null=True, blank=True)
    inquiry_content = models.TextField(null=True, blank=True)
    created_at_utc = models.DateTimeField(null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True)
    answered = models.BooleanField(default=False)
    answer_content = models.TextField(null=True, blank=True)
    orderId01 = models.CharField(max_length=100, null=True, blank=True)
    product_id = models.CharField(max_length=100, null=True, blank=True)
    product_name = models.CharField(max_length=255, null=True, blank=True)
    option_name = models.CharField(max_length=255, null=True, blank=True)
    author = models.CharField(max_length=100, null=True, blank=True)
    customer_name = models.CharField(max_length=100, null=True, blank=True)
    store_name = models.CharField(max_length=255, null=True, blank=True)
    orderId02 = models.CharField(max_length=100, null=True, blank=True)
    answer_date = models.DateTimeField(null=True, blank=True)
    representative_image = models.CharField(max_length=255, null=True, blank=True)
    ordered_at = models.DateTimeField(null=True, blank=True)
    platform = models.CharField(max_length=50, null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    answer_updated_at = models.DateTimeField(null=True, blank=True)
    gpt_summary = models.TextField(null=True, blank=True)
    gpt_recommendation_1 = models.TextField(null=True, blank=True)
    gpt_recommendation_2 = models.TextField(null=True, blank=True)
    gpt_confidence_score = models.FloatField(null=True, blank=True)
    gpt_used_answer_index = models.IntegerField(null=True, blank=True)
    inquiry_status = models.CharField(max_length=50, null=True, blank=True)  
    partner_transfer_status = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"CenterInquiry #{self.inquiry_id} - {self.inquiry_title or 'No Title'}"
