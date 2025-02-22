from django.db import models
from django.db.models import Q

class CoupangProduct(models.Model):
    """
    'data' 하위의 상단 레벨 정보:
    - sellerProductId, sellerProductName, displayCategoryCode, vendorId, 등
    """
    code = models.CharField(max_length=50, blank=True, null=True)
    message = models.CharField(max_length=255, blank=True, null=True)

    sellerProductId = models.BigIntegerField(null=True, blank=True)
    categoryId = models.BigIntegerField(null=True, blank=True)
    productId = models.BigIntegerField(null=True, blank=True)
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
    rocket_vendor_item_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )
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
    marketplace_vendor_item_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )
    marketplace_item_id = models.BigIntegerField(null=True, blank=True)
    marketplace_barcode = models.CharField(max_length=255, blank=True, null=True)
    marketplace_maximum_buy_count = models.IntegerField(null=True, blank=True, default=0)
    marketplace_model_no = models.CharField(max_length=100, blank=True, null=True)

    marketplace_original_price = models.IntegerField(default=0)
    marketplace_sale_price = models.IntegerField(default=0)
    marketplace_supply_price = models.IntegerField(default=0)

    marketplace_best_price_guaranteed_3p = models.BooleanField(default=False)
    marketplace_external_vendor_sku = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['rocket_vendor_item_id'],
                name='unique_rocket_vendor_item_id_not_null',
                condition=Q(rocket_vendor_item_id__isnull=False)
            ),
            models.UniqueConstraint(
                fields=['marketplace_vendor_item_id'],
                name='unique_market_vendor_item_id_not_null',
                condition=Q(marketplace_vendor_item_id__isnull=False)
            ),
        ]

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


class CoupangDailySales(models.Model):
    displayed_product_id = models.CharField("Displayed Product ID", max_length=255)
    
    # 1) SKU ID: 소수점 필요없는 문자열로 (CharField)
    sku_id = models.CharField("SKU ID", max_length=255)

    # 2) item_name는 기존 그대로 유지하되, 
    #    product_name / option_name을 새로 추가하여 "쉼표 분리"된 부분을 저장할 예정
    item_name = models.CharField("itemName", max_length=255)
    product_name = models.CharField("Product Name", max_length=255, blank=True, null=True)
    option_name = models.CharField("Option Name", max_length=255, blank=True, null=True)

    delivery_label = models.CharField("delivery_label", max_length=255)
    category_name = models.CharField("category name", max_length=255)

    # (기존) 아이템 위너 비율 (소수점 2자리 필요 시 유지)
    item_winner_ratio = models.DecimalField("Item Winner Ratio", max_digits=5, decimal_places=2)

    # 3) 소수점 없이 저장할 필드들 (BigIntegerField 권장)
    net_sales_amount = models.BigIntegerField("Net Sales Amount")
    net_sold_items = models.IntegerField("Net Sold Items")

    total_transaction_amount = models.BigIntegerField("Total Transaction Amount")
    total_transaction_items = models.IntegerField("Total Transaction Items")

    total_cancellation_amount = models.BigIntegerField("Total Cancellation Amount")
    total_cancelled_items = models.IntegerField("Total Cancelled Items")

    immediate_cancellation_items = models.IntegerField("Immediate Cancellation Items")

    date = models.DateField("Date")

    def __str__(self):
        return f"{self.displayed_product_id} - {self.date}"
    



class AdsReport(models.Model):
    """
    광고 보고서 테이블
    """
    report_date = models.DateField("날짜")

    delivery_label = models.CharField(
        "구분(delivery_label)", 
        max_length=50, 
        blank=True, 
        null=True
    )
    
    sold_items = models.IntegerField(
        "판매수량(sold_items)", 
        default=0
    )
    ads_sold_items = models.IntegerField(
        "광고판매수량(ads_sold_items)", 
        default=0
    )
    
    # 전환률(%) → ex: 12.34%
    conversion_rate = models.DecimalField(
        "전환률(conversion_rate)", 
        max_digits=5,     # 예: 최대 999.99% 가능
        decimal_places=2, 
        default=0.00
    )
    
    total_transaction_amount = models.IntegerField(
        "매출(total_transaction_amount)",
        default=0
    )
    ads_total_transaction_amount = models.IntegerField(
        "광고집행매출(ads_total_transaction_amount)",
        default=0
    )
    ad_spend = models.IntegerField(
        "광고집행비(ad_spend)",
        default=0
    )
    net_sales_amount = models.IntegerField(
        "순이익금(net_sales_amount)",
        default=0
    )
    
    # 상품/옵션 관련
    product_name = models.CharField(
        "상품명(product_name)",
        max_length=255,
        blank=True,
        null=True
    )
    option_name = models.CharField(
        "옵션명(option_name)",
        max_length=255,
        blank=True,
        null=True
    )
    item_name = models.CharField(
        "item_name",
        max_length=255,
        blank=True,
        null=True
    )
    
    # SKU/옵션코드/item_id
    sku_id = models.CharField(
        "sku_id",
        max_length=255,
        blank=True,
        null=True
    )
    external_vendor_sku = models.CharField(
        "옵션코드(external_vendor_sku)",
        max_length=255,
        blank=True,
        null=True
    )
    item_id = models.CharField("item_id",max_length=255,blank=True,null=True)

    def __str__(self):
        return f"{self.date} - {self.product_name or '-'} / {self.option_name or '-'}"
    


class CoupangAdsReport(models.Model):
    """
    쿠팡 광고 리포트 (엑셀 업로드용)
    """
    # 날짜
    date = models.DateField("Date")
    
    # 광고유형
    ad_type = models.CharField("Ad Type", max_length=100, blank=True, null=True)
    
    # 캠페인 ID
    campaign_id = models.CharField("Campaign ID", max_length=100, blank=True, null=True)
    
    # 캠페인명
    campaign_name = models.CharField("Campaign Name", max_length=255, blank=True, null=True)
    
    # 광고그룹
    ad_group = models.CharField("Ad Group", max_length=255, blank=True, null=True)
    
    # 광고집행 상품명
    executed_product_name = models.CharField("Executed Product Name", max_length=255, blank=True, null=True)
    
    # 광고집행 옵션ID
    executed_option_id = models.CharField("Executed Option ID", max_length=100, blank=True, null=True)

    product_name = models.CharField("product_name", max_length=255, blank=True, null=True)
    option_name = models.CharField("option_name", max_length=255, blank=True, null=True)
    
    # 광고전환매출발생 상품명
    converting_product_name = models.CharField("Converting Product Name", max_length=255, blank=True, null=True)
    
    # 광고전환매출발생 옵션ID
    converting_option_id = models.CharField("Converting Option ID", max_length=100, blank=True, null=True)
    
    # 광고 노출 지면
    ad_placement = models.CharField("Ad Placement", max_length=255, blank=True, null=True)
    
    # 노출수
    impressions = models.IntegerField("Impressions", default=0)
    
    # 클릭수
    clicks = models.IntegerField("Clicks", default=0)
    
    
    # 클릭률(CTR) - 예) 15.37% → 15.37 형태로 저장
    ctr = models.DecimalField("CTR (Click-Through Rate)", max_digits=6, decimal_places=2, default=0.00)
    
    # 총 주문수(1일)
    orders = models.IntegerField("Orders", default=0)
    
    # 총 판매수량(1일)
    sold_quantity = models.IntegerField("Sold Quantity", default=0)
    
    # 총 전환매출액(1일) 
    sales_amount = models.IntegerField("Sales Amount", default=0)

    # 광고비
    ad_spend = models.IntegerField("Ad Spend", default=0)
    
    # 총광고수익률(1일) (ROAS)
    roas = models.DecimalField("ROAS", max_digits=8, decimal_places=2, default=0.00)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'date',
                    'converting_option_id',
                    'impressions',
                    'clicks',
                    'ad_spend',
                    'orders'
                ],
                name='unique_report_by_date_option_imp_click_spend_orders'
            )
        ]
    
    def __str__(self):
        return f"{self.date} | {self.converting_option_id} | Imp={self.impressions}"
    
    def save(self, *args, **kwargs):
        # 새로운 객체일 때 광고비에 부가세 10%(1.1배)를 적용하여 저장합니다.
        if not self.pk:
            self.ad_spend = int(self.ad_spend * 1.1)
        super().save(*args, **kwargs)
    


class PurchaseCost(models.Model):
    """
    SKU 단위 매입가 정보.
    -> sku_id 가 unique
    -> option_code : rocket_external_vendor_sku / marketplace_external_vendor_sku
    """
    sku_id = models.CharField(max_length=100)
    option_code = models.CharField(max_length=100, blank=True, null=True)
    manager = models.CharField(max_length=50, blank=True, null=True)
    purchasing_price = models.IntegerField(default=0)

    class Meta:
        db_table = 'purchase_cost'

    def __str__(self):
        return f"[SKU={self.sku_id}] (option={self.option_code}) => {self.purchasing_price}"
    

class CostModel(models.Model):
        option_code = models.CharField(max_length=100, unique=True)
        manager = models.CharField(max_length=50, blank=True, null=True)
        fee = models.IntegerField(default=0)
        purchase_price = models.IntegerField(default=0)
        rocket_cost = models.IntegerField(default=0)
        traffic_cost = models.IntegerField(default=0)
        shipping_cost = models.IntegerField(default=0)
        ad_cost = models.IntegerField(default=0)
        ad_cost_01 = models.IntegerField(default=0)
        ad_cost_02 = models.IntegerField(default=0)
        ad_cost_03 = models.IntegerField(default=0)
        discount_cost = models.IntegerField(default=0)
        coupon_cost = models.IntegerField(default=0)
        etc_cost_01 = models.IntegerField(default=0)
        etc_cost_02 = models.IntegerField(default=0)
        etc_cost_03 = models.IntegerField(default=0)
        inout_cost = models.IntegerField(default=0)
        storage_cost = models.IntegerField(default=0)

        class Meta:
            db_table = 'cost_model'            