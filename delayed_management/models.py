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
    ('webhook','대기중'),
    ('dupli','중복'),
]

SEND_STATUS_CHOICES = [
    ('none', '발송 전'),
    ('pending', '대기'),
    ('success', '성공'),
    ('failed', '실패'),
]

FLOW_STATUS_CHOICES = [
    ('pre_send', '발송전'),
    ('sent', '발송완료'),
    ('confirmed', '확인완료'),
    ('shipped', '출고완료'),
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
    flow_status = models.CharField(
        max_length=20,
        choices=FLOW_STATUS_CHOICES,
        default='pre_send'  # 초깃값: 발송 전
    )
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
    changed_option_code = models.CharField(max_length=100, blank=True, null=True)
    message_sent_at = models.DateTimeField(null=True, blank=True)  # 문자 발송된 시간
    solapi_group_id = models.CharField(max_length=60, blank=True, null=True)


    def __str__(self):
        return f"{self.option_code} - {self.customer_name}"

    @property
    def status_display(self):
        # STATUS_CHOICES의 label 반환
        return dict(STATUS_CHOICES).get(self.status, '알수없음')

# models.py
class ExternalPlatformMapping(models.Model):
    """
    옵션코드와 외부몰(네이버, 쿠팡, 11번가 등) 간의 매핑 정보.
    """
    option_code = models.CharField(max_length=100)  # 내부 시스템의 옵션코드
    platform_name = models.CharField(max_length=50) # 예: "NAVER", "COUPANG", ...
    platform_product_id = models.CharField(max_length=100, blank=True, null=True)
    platform_option_id = models.CharField(max_length=100, blank=True, null=True)

    # 예: 품절 여부, 재고수량 캐싱, etc.
    is_out_of_stock = models.BooleanField(default=False)
    last_known_stock = models.IntegerField(default=0)   # 최근에 확인한 플랫폼 재고
    updated_at = models.DateTimeField(auto_now=True)
    # 재고 필드들 (초기값=0)
    niedlich_stock = models.IntegerField(default=0)
    subida_stock = models.IntegerField(default=0)
    nonegae_stock = models.IntegerField(default=0)
    arbing_stock = models.IntegerField(default=0)
    coupang01_stock = models.IntegerField(default=0)
    coupang02_stock = models.IntegerField(default=0)
    store_stock = models.IntegerField(default=0)

    # 예시: 셀러툴 재고
    seller_tool_stock = models.IntegerField(default=0)


    def __str__(self):
        return self.option_code

    def __str__(self):
        return f"{self.option_code} / {self.platform_name} / {self.platform_option_id}"

class StockLog(models.Model):
    option_code = models.CharField(max_length=100)
    platform = models.CharField(max_length=50)       # NAVER, COUPANG, ...
    action = models.CharField(max_length=50)         # '품절처리', '판매재개', '재고확인' 등
    old_stock = models.IntegerField(default=0)
    new_stock = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.created_at}] {self.option_code} / {self.platform} / {self.action} {self.old_stock}->{self.new_stock}"


class ExternalProductItem(models.Model):
    origin_product_no = models.BigIntegerField(unique=True)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    representative_image = models.URLField(blank=True, null=True)
    sale_price = models.IntegerField(blank=True, null=True)
    stock_quantity = models.IntegerField(blank=True, null=True)
    seller_code_info = models.CharField(max_length=255, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.origin_product_no}] {self.product_name}"

class ExternalProductOption(models.Model):
    product = models.ForeignKey(
        ExternalProductItem, 
        on_delete=models.CASCADE, 
        related_name='options'
    )
    option_id = models.CharField(max_length=100, blank=True, null=True)
    option_name1 = models.CharField(max_length=255, blank=True, null=True)
    option_name2 = models.CharField(max_length=255, blank=True, null=True)
    stock_quantity = models.IntegerField(default=0)
    price = models.IntegerField(default=0)
    seller_manager_code = models.CharField(max_length=255, blank=True, null=True)
    seller_tool_stock = models.IntegerField(default=0)  # 새로운 필드 추가
    store_name = models.CharField(max_length=100, blank=True)

    # ▼ 추가: (product, option_id) 쌍을 유니크하게
    class Meta:
        unique_together = (("product", "option_id"), )

    def __str__(self):
        return f"{self.product.product_name} / {self.option_name1} / {self.option_name2}"


class OptionMapping(models.Model):
    """
    내부에서 사용하는 메인 "옵션코드" 중심 모델.
    (우리 쪽 고유의 option_code)
    """
    option_code = models.CharField(max_length=100, unique=True)

    # 추가 정보들 (기존 필드)
    order_product_name  = models.CharField(max_length=200, blank=True)
    order_option_name   = models.CharField(max_length=200, blank=True)
    store_name          = models.CharField(max_length=100, blank=True)
    seller_product_name = models.CharField(max_length=200, blank=True)
    seller_option_name  = models.CharField(max_length=200, blank=True)
    expected_date       = models.CharField(max_length=200, blank=True)
    expected_start      = models.DateField(null=True, blank=True)
    expected_end        = models.DateField(null=True, blank=True)
    updated_at          = models.DateTimeField(auto_now=True)
    base_sale_price     = models.IntegerField(default=0, blank=True, null=True)
    discounted_price    = models.IntegerField(default=0, blank=True, null=True)

    def __str__(self):
        return f"{self.option_code}"


class OptionPlatformDetail(models.Model):
    """
    하나의 "option_code(OptionMapping)"에 대해,
    여러 플랫폼(스토어)별로 다른 옵션ID / 재고 / 가격 / 이미지 ... 
    등등을 1:N 형태로 저장하는 테이블.
    """
    option_mapping = models.ForeignKey(
        OptionMapping,
        on_delete=models.CASCADE,
        related_name='platform_details'
    )
    platform_name = models.CharField(max_length=50)
    platform_product_id = models.CharField(max_length=100, blank=True, null=True)
    platform_option_id  = models.CharField(max_length=100, blank=True, null=True)

    order_product_name  = models.CharField(max_length=200, blank=True, null=True)
    order_option_name   = models.CharField(max_length=200, blank=True, null=True)
    # 아래 부분 오타 중복에 주의(사용자 코드에 보면 order_option_name이 2번 나왔는데, 하나 제거 필요)
    stock               = models.IntegerField(default=0)
    price               = models.IntegerField(default=0)
    seller_manager_code = models.CharField(max_length=255, blank=True, null=True)
    representative_image= models.URLField(blank=True, null=True)
    origin_product_no   = models.CharField(max_length=100, blank=True, null=True)
    updated_at          = models.DateTimeField(auto_now=True)
    seller_tool_stock   = models.IntegerField(default=0)  # 새로운 필드 추가
    out_of_stock_at = models.DateTimeField(null=True, blank=True)


    def __str__(self):
        return (
            f"[{self.platform_name}] "
            f"option_id={self.platform_option_id}, "
            f"stock={self.stock}, price={self.price}"
        )

class OutOfStockMapping(models.Model):
    option_code = models.CharField(max_length=100, db_index=True)
    order_product_name = models.CharField(max_length=200, blank=True)
    order_option_name  = models.CharField(max_length=200, blank=True)
    store_name         = models.CharField(max_length=100, blank=True)
    seller_product_name= models.CharField(max_length=200, blank=True)
    seller_option_name = models.CharField(max_length=200, blank=True)
    expected_date      = models.CharField(max_length=200, blank=True)
    updated_at         = models.DateTimeField(auto_now=True)
    out_of_stock_at    = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"[OutOfStock] {self.option_code}"
    
class OutOfStock(models.Model):
    status = models.IntegerField(default=0, verbose_name="표시상태")
    platform_name = models.CharField(max_length=100, verbose_name='플랫폼명')
    representative_image = models.URLField(max_length=500, blank=True, null=True, verbose_name='대표이미지')
    product_id = models.CharField(max_length=50, verbose_name='상품ID')
    option_id = models.CharField(max_length=50, unique=True, verbose_name='옵션ID')
    option_id_stock = models.IntegerField(default=0, verbose_name='옵션ID재고')
    seller_tool_stock = models.IntegerField(default=0, verbose_name='셀러툴재고')
    expected_restock_date = models.DateTimeField(blank=True, null=True, verbose_name='예상날짜')
    order_product_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='주문상품명')
    order_option_name_01 = models.CharField(max_length=200, blank=True, null=True, verbose_name='주문옵션명01')
    order_option_name_02 = models.CharField(max_length=200, blank=True, null=True, verbose_name='주문옵션명02')
    seller_product_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='셀러툴상품명')
    seller_option_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='셀러툴옵션명')
    option_code = models.CharField(max_length=100, blank=True, null=True, verbose_name='옵션코드')
    original_price = models.IntegerField(default=0, verbose_name='정가')
    sale_price     = models.IntegerField(default=0, verbose_name='할인가')
    add_option_price = models.IntegerField(default=0, verbose_name='추가옵션가')
    out_of_stock_at = models.DateTimeField(blank=True, null=True, verbose_name='품절처리시간')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='업데이트시간')
    class Meta:
        verbose_name = '재고품절'
        verbose_name_plural = '재고품절 목록'
    def __str__(self): return f"[{self.platform_name}] {self.product_id} (옵션ID={self.option_id})"


class OutOfStockCheck(models.Model):
    status = models.IntegerField(default=0, verbose_name="표시상태")
    platform_name = models.CharField(max_length=100, verbose_name='플랫폼명')
    representative_image = models.URLField(max_length=500, blank=True, null=True, verbose_name='대표이미지')
    product_id = models.CharField(max_length=50, verbose_name='상품ID')
    option_id = models.CharField(max_length=50, unique=True, verbose_name='옵션ID')
    option_id_stock = models.IntegerField(default=0, verbose_name='옵션ID재고')
    seller_tool_stock = models.IntegerField(default=0, verbose_name='셀러툴재고')
    expected_restock_date = models.DateTimeField(blank=True, null=True, verbose_name='예상날짜')
    order_product_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='주문상품명')
    order_option_name_01 = models.CharField(max_length=200, blank=True, null=True, verbose_name='주문옵션명01')
    order_option_name_02 = models.CharField(max_length=200, blank=True, null=True, verbose_name='주문옵션명02')
    seller_product_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='셀러툴상품명')
    seller_option_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='셀러툴옵션명')
    option_code = models.CharField(max_length=100, blank=True, null=True, verbose_name='옵션코드')
    original_price = models.IntegerField(default=0, verbose_name='정가')
    sale_price     = models.IntegerField(default=0, verbose_name='할인가')
    add_option_price = models.IntegerField(default=0, verbose_name='추가옵션가')
    out_of_stock_at = models.DateTimeField(blank=True, null=True, verbose_name='품절처리시간')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='업데이트시간')
    class Meta:
        verbose_name = '품절확인'
        verbose_name_plural = '품절확인 목록'
    def __str__(self): return f"[{self.platform_name}] {self.product_id} (옵션ID={self.option_id})"