from django.db import models

class ProductOptionMapping(models.Model):
    option_code = models.CharField(max_length=100)
    product_name = models.CharField(max_length=255)
    option_name = models.CharField(max_length=255)
    store_name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.option_code} - {self.product_name}/{self.option_name}"

class DelayedOrder(models.Model):
    option_code = models.CharField(max_length=100)
    customer_name = models.CharField(max_length=100)
    customer_contact = models.CharField(max_length=100)
    order_product_name = models.CharField(max_length=255, blank=True)
    order_option_name = models.CharField(max_length=255, blank=True)
    quantity = models.CharField(max_length=50, blank=True)  # 수량 필드
    seller_product_name = models.CharField(max_length=255, blank=True)
    seller_option_name = models.CharField(max_length=255, blank=True)
    order_number_1 = models.CharField(max_length=255, blank=True)
    order_number_2 = models.CharField(max_length=255, blank=True)
    store_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.option_code} - {self.customer_name}"

class OptionStoreMapping(models.Model):
    option_code = models.CharField(max_length=100)
    store_name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.option_code} -> {self.store_name}"

STATUS_CHOICES = [
    ('purchase', '구매된상품들'),  # 14~21일
    ('shipping', '배송중'),       # 10~14일
    ('arrived', '도착완료'),      # 7~10일
    ('document', '서류작성'),     # 5~7일
    ('loading', '선적중'),        # 1~4일
    ('nopurchase', '미구매'),  # ← 새로 추가
]

SEND_TYPE_CHOICES = [
    ('none', '미발송'),
    ('sms', '문자'),
    ('kakao', '알림톡'),
]

SEND_STATUS_CHOICES = [
    ('none', '발송 전'),
    ('pending', '대기'),
    ('success', '성공'),
    ('failed', '실패'),
]

class DelayedShipmentGroup(models.Model):
    """
    같은 고객 / 같은 주문에 대해 하나의 그룹으로 묶기
    """
    token = models.CharField(max_length=100, unique=True, blank=True, null=True)
    contact = models.CharField(max_length=100, blank=True)  # 고객 연락처
    # 예: 아래 필드들은 필요 시 추가
    # customer_name = models.CharField(max_length=100, blank=True)
    # store_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    shipments = models.ManyToManyField('DelayedShipment', related_name='shipment_groups')

    def __str__(self):
        return f"Group {self.id} / token={self.token}"
    
class DelayedShipment(models.Model):
    # 공통 필드
    option_code = models.CharField(max_length=100)  # 필요에 따라 unique 제거 가능
    order_option_name = models.CharField(max_length=255, blank=True)  # 셀러툴 옵션명
    order_product_name = models.CharField(max_length=255, blank=True)
    seller_product_name = models.CharField(max_length=255, blank=True)
    seller_option_name = models.CharField(max_length=255, blank=True)
    order_number_1 = models.CharField(max_length=100, blank=True)
    order_number_2 = models.CharField(max_length=100, blank=True)
    quantity = models.CharField(max_length=50, blank=True)

    # 교환 가능 옵션 필드
    exchangeable_options = models.TextField(blank=True)  # 콤마 구분 문자열 등

    # “재입고 안내날짜” → 한 번 정해지면 변경되지 않음
    restock_date = models.DateField(null=True, blank=True)  

    # “재입고 예상날짜” → 동기화 시마다 갱신 (새로 추가)
    expected_restock_date = models.DateField(null=True, blank=True)

    # 추가 정보
    store_name = models.CharField(max_length=255, blank=True)
    customer_name = models.CharField(max_length=100, blank=True)
    customer_contact = models.CharField(max_length=100, blank=True)
    changed_option = models.CharField(max_length=255, blank=True)  # 고객이 선택한 새로운 옵션
    waiting = models.BooleanField(default=False)  # 기다리기 여부
    confirmed = models.BooleanField(default=False)  # 확인 여부
    created_at = models.DateTimeField(auto_now_add=True)

    # 상태(구매된상품들, 배송중, 도착완료, 서류작성, 선적중 등)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='nopurchase')
    # ▼ 새로 추가
    send_type = models.CharField(
        max_length=10, 
        choices=SEND_TYPE_CHOICES, 
        default='NONE',
        help_text="문자(SMS), 알림톡(KAKAO), 혹은 미전송(NONE) 등"
    )
    send_status = models.CharField(
        max_length=10,
        choices=SEND_STATUS_CHOICES,
        default='NONE',
        help_text="전송 상태(대기, 전송중, 성공, 실패)"
    )

    # 추가: 문자/알림톡 발송 후 고객 확인용 토큰
    token = models.CharField(max_length=200, blank=True, null=True)


    def __str__(self):
        return f"{self.option_code} - {self.customer_name}"

    @property
    def status_display(self):
        # STATUS_CHOICES의 label 반환
        return dict(STATUS_CHOICES).get(self.status, '알수없음')

