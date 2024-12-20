from django.db import models

class ProductOptionMapping(models.Model):
    option_code = models.CharField(max_length=100, unique=True)
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
    option_code = models.CharField(max_length=100, unique=True)
    store_name = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.option_code} -> {self.store_name}"

class DelayedShipment(models.Model):
    option_code = models.CharField(max_length=100)
    order_option_name = models.CharField(max_length=255, blank=True)  # 셀러툴 옵션명
    exchangeable_options = models.TextField(blank=True)  # 교환가능옵션(콤마 구분 문자열 등)
    restock_date = models.DateField(null=True, blank=True)  # 재입고일자
    store_name = models.CharField(max_length=255, blank=True)
    customer_name = models.CharField(max_length=100, blank=True)
    customer_contact = models.CharField(max_length=100, blank=True)
    changed_option = models.CharField(max_length=255, blank=True)  # 고객이 선택한 새로운 옵션
    waiting = models.BooleanField(default=False)  # 기다리기 여부
    confirmed = models.BooleanField(default=False)  # 확인여부
    created_at = models.DateTimeField(auto_now_add=True)
    # 추가 필드 (들여쓰기 맞춰줌)
    order_product_name = models.CharField(max_length=255, blank=True)
    seller_product_name = models.CharField(max_length=255, blank=True)
    seller_option_name = models.CharField(max_length=255, blank=True)
    order_number_1 = models.CharField(max_length=100, blank=True)
    order_number_2 = models.CharField(max_length=100, blank=True)
    quantity = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.option_code} - {self.customer_name}"
