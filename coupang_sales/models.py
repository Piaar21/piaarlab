from django.db import models

class CoupangProduct(models.Model):
    """
    'data' 하위의 상단 레벨 정보:
    - sellerProductId, sellerProductName, displayCategoryCode, vendorId, 등
    """
    code = models.CharField(max_length=50, blank=True, null=True)
    message = models.CharField(max_length=255, blank=True, null=True)

    sellerProductId = models.BigIntegerField(null=True, blank=True)
    sellerProductName = models.CharField(max_length=255, blank=True, null=True)
    displayCategoryCode = models.BigIntegerField(null=True, blank=True)
    vendorId = models.CharField(max_length=50, blank=True, null=True)
    brand = models.CharField(max_length=255, blank=True, null=True)
    productGroup = models.CharField(max_length=255, blank=True, null=True)
    statusName = models.CharField(max_length=50, blank=True, null=True)
    vendorUserId = models.CharField(max_length=100, blank=True, null=True)
    requested = models.BooleanField(default=False)

    # created_at, updated_at 등 필요한 필드
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.sellerProductId}] {self.sellerProductName}"


class CoupangItem(models.Model):
    """
    'items' 배열의 각 원소를 저장하는 모델.
    - 기본 itemName, unitCount, outboundShippingTime 등
    - rocketGrowthItemData / marketplaceItemData의 필드를 각각 나눠서 저장
    - vendorItemId(rocket, marketplace)를 중요 식별자로 관리
    """
    parent = models.ForeignKey(
        CoupangProduct, 
        on_delete=models.CASCADE,
        related_name='items'
    )

    # 공통
    itemName = models.CharField(max_length=255, blank=True, null=True)
    unitCount = models.IntegerField(default=1)
    outboundShippingTime = models.IntegerField(default=0)

    # rocketGrowthItemData
    rocket_seller_product_item_id = models.BigIntegerField(null=True, blank=True)
    rocket_vendor_item_id = models.BigIntegerField(null=True, blank=True)  # <--- 기준 vendorItemId(로켓배송용)
    rocket_item_id = models.BigIntegerField(null=True, blank=True)
    rocket_external_vendor_sku = models.CharField(max_length=255, blank=True, null=True)
    rocket_barcode = models.CharField(max_length=255, blank=True, null=True)
    rocket_model_no = models.CharField(max_length=100, blank=True, null=True)

    rocket_original_price = models.IntegerField(null=True, blank=True, default=0)
    rocket_sale_price = models.IntegerField(null=True, blank=True, default=0)
    rocket_supply_price = models.IntegerField(null=True, blank=True, default=0)

    # rocket_skuInfo
    rocket_height = models.IntegerField(null=True, blank=True, default=0)
    rocket_length = models.IntegerField(null=True, blank=True, default=0)
    rocket_width = models.IntegerField(null=True, blank=True, default=0)
    rocket_weight = models.IntegerField(null=True, blank=True, default=0)
    rocket_quantity_per_box = models.IntegerField(null=True, blank=True, default=1)

    rocket_stand_alone = models.BooleanField(null=True, blank=True, default=False)
    rocket_distribution_period = models.IntegerField(null=True, blank=True, default=0)
    rocket_expired_at_managed = models.BooleanField(null=True, blank=True, default=False)
    rocket_manufactured_at_managed = models.BooleanField(null=True, blank=True, default=False)

    rocket_net_weight = models.IntegerField(null=True, blank=True)   # None이면 미관리 (필요 시 default=0 가능)
    rocket_heat_sensitive = models.BooleanField(null=True, blank=True)  # None이면 정보없음
    rocket_hazardous = models.BooleanField(null=True, blank=True)       # None이면 정보없음

    rocket_original_barcode = models.CharField(max_length=255, blank=True, null=True)
    rocket_maximum_buy_count = models.IntegerField(null=True, blank=True, default=0)
    rocket_inbound_name = models.CharField(max_length=255, blank=True, null=True)
    rocket_original_dimension_input_type = models.CharField(max_length=50, blank=True, null=True)


    # marketplaceItemData
    marketplace_seller_product_item_id = models.BigIntegerField(null=True, blank=True)
    marketplace_vendor_item_id = models.BigIntegerField(null=True, blank=True)  # <--- 기준 vendorItemId(마켓플레이스용)
    marketplace_item_id = models.BigIntegerField(null=True, blank=True)
    marketplace_barcode = models.CharField(max_length=255, blank=True, null=True)
    marketplace_maximum_buy_count = models.IntegerField(null=True, blank=True, default=0)
    marketplace_model_no = models.CharField(max_length=100, blank=True, null=True)

    marketplace_original_price = models.IntegerField(default=0)
    marketplace_sale_price = models.IntegerField(default=0)
    marketplace_supply_price = models.IntegerField(default=0)

    marketplace_best_price_guaranteed_3p = models.BooleanField(default=False)
    marketplace_external_vendor_sku = models.CharField(max_length=255, blank=True, null=True)
    def __str__(self):
        return f"Item: {self.itemName} (rocketVendor={self.rocket_vendor_item_id}, marketVendor={self.marketplace_vendor_item_id})"


class CoupangItemImage(models.Model):
    """
    각 item의 'images' 배열.
    """
    parent_item = models.ForeignKey(
        CoupangItem, 
        on_delete=models.CASCADE,
        related_name='images'
    )
    imageOrder = models.IntegerField(default=0)
    imageType = models.CharField(max_length=50, blank=True, null=True)
    cdnPath = models.CharField(max_length=255, blank=True, null=True)
    vendorPath = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Image {self.imageOrder} of item={self.parent_item.id}"
