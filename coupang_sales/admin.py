from django.contrib import admin
from .models import CoupangProduct, CoupangItem, CoupangItemImage

@admin.register(CoupangItem)
class CoupangItemAdmin(admin.ModelAdmin):
    """
    옵션(CoupangItem) 중심으로 관리.
    모든 열을 list_display로 구성하여, 
    '상품ID', 'SKU ID', 'custom ID', '구분', '상품명(옵션명)', '판매가/할인가', '개당이익금', ...
    """
    
    list_display = (
        'id',
        'get_seller_product_id',     # 상품ID
        'get_sku_id',                # SKU ID
        'get_custom_id',             # custom ID
        'get_label_type',            # 구분(로켓/판매자/둘다)
        'get_product_name',          # 상품명(상위 Product)
        'get_sale_price_display',    # 판매가(할인가)
        'get_original_price_display',# 할인가
        'get_profit_display',        # 개당이익금
        'get_fee_display',           # 마켓 수수료
        'get_inout_charge',          # 입출고요금
        'get_cost',                  # 원가(여기서는 '-')
        'get_delivery_charge',       # 배송비
        'get_status_display',        # 상태
    )
    search_fields = (
        'itemName',
        'rocket_vendor_item_id',
        'marketplace_vendor_item_id',
        'rocket_external_vendor_sku',
        'marketplace_external_vendor_sku',
        'parent__sellerProductName',
    )
    
    # 읽기전용/정렬 등 설정은 필요시 추가
    
    # (A) 상품ID
    def get_seller_product_id(self, obj):
        if obj.parent:
            return obj.parent.sellerProductId
        return '-'
    get_seller_product_id.short_description = "상품ID"

    # (B) SKU ID (rocket_vendor_item_id or marketplace_vendor_item_id)
    def get_sku_id(self, obj):
        return obj.rocket_vendor_item_id or obj.marketplace_vendor_item_id or '-'
    get_sku_id.short_description = "SKU ID"
    
    # (C) custom ID (rocket_external_vendor_sku or marketplace_external_vendor_sku)
    def get_custom_id(self, obj):
        return obj.rocket_external_vendor_sku or obj.marketplace_external_vendor_sku or '-'
    get_custom_id.short_description = "custom ID"
    
    # (D) 구분(로켓/판매자/둘다)
    def get_label_type(self, obj):
        rocket_exists = bool(obj.rocket_vendor_item_id)
        market_exists = bool(obj.marketplace_vendor_item_id)
        if rocket_exists and market_exists:
            return "로켓&판매자"
        elif rocket_exists:
            return "로켓그로스"
        else:
            return "판매자배송"
    get_label_type.short_description = "구분"

    # (E) 상품명(옵션명) → 사실 itemName가 옵션명이라면, 상위 상품명은 parent.sellerProductName
    def get_product_name(self, obj):
        # 만약 "상품명" = 상위 Product의 sellerProductName 을 표시하려면:
        if obj.parent:
            return obj.parent.sellerProductName or '-'
        # 만약 "옵션명"을 표시하려면 obj.itemName
        return '-'
    get_product_name.short_description = "상품명"

    # (F) 판매가(할인가) → rocket_sale_price or marketplace_sale_price
    def get_sale_price_display(self, obj):
        sale_price = obj.rocket_sale_price or obj.marketplace_sale_price or 0
        return f"{sale_price:,.2f} 원" if sale_price else '-'
    get_sale_price_display.short_description = "판매가(할인가)"

    # (G) 할인가(originalPrice)
    def get_original_price_display(self, obj):
        original_price = obj.rocket_original_price or obj.marketplace_original_price or 0
        if original_price:
            return f"{original_price:,.2f} 원"
        return '-'
    get_original_price_display.short_description = "할인가"

    # (H) 마켓 수수료 (예: 11.88%)
    def get_fee_display(self, obj):
        # sale_price
        sp = obj.rocket_sale_price or obj.marketplace_sale_price or 0
        fee_rate = 0.1188
        fee_amount = sp * fee_rate
        if sp > 0:
            return f"{fee_amount:,.2f} 원"
        return '-'
    get_fee_display.short_description = "마켓 수수료"

    # (I) 개당이익금 = salePrice - fee
    def get_profit_display(self, obj):
        sp = obj.rocket_sale_price or obj.marketplace_sale_price or 0
        fee_rate = 0.1188
        fee_amount = sp * fee_rate
        profit = sp - fee_amount
        if sp > 0:
            return f"{profit:,.2f} 원"
        return '-'
    get_profit_display.short_description = "개당이익금"

    # (J) 입출고요금(로켓그로스거나 로켓&판매자일 때 표시)
    def get_inout_charge(self, obj):
        rocket_exists = bool(obj.rocket_vendor_item_id)
        market_exists = bool(obj.marketplace_vendor_item_id)
        if rocket_exists:  # 혹은 rocket_exists and market_exists
            return "1,072 원"
        return '-'
    get_inout_charge.short_description = "입출고요금"

    # (K) 원가(추후), 여기서는 일단 '-'
    def get_cost(self, obj):
        return "-"
    get_cost.short_description = "원가"

    # (L) 배송비 (상위 product.deliveryCharge)
    def get_delivery_charge(self, obj):
        if obj.parent and hasattr(obj.parent, 'deliveryCharge'):
            dc = getattr(obj.parent, 'deliveryCharge', 0) or 0
            if dc > 0:
                return f"{dc} 원"
        return '-'
    get_delivery_charge.short_description = "배송비"

    # (M) 상태: rocket_maximum_buy_count or marketplace_maximum_buy_count
    def get_status_display(self, obj):
        rocket_cnt = obj.rocket_maximum_buy_count or 0
        market_cnt = obj.marketplace_maximum_buy_count or 0
        if rocket_cnt > 0 or market_cnt > 0:
            return "판매중"
        return "품절"
    get_status_display.short_description = "상태"


@admin.register(CoupangProduct)
class CoupangProductAdmin(admin.ModelAdmin):
    """
    상품 Admin (원한다면)
    간단히 sellerProductId, sellerProductName 등만 볼 수 있음
    """
    list_display = ('id', 'sellerProductId', 'sellerProductName', 'brand', 'statusName')
    search_fields = ('sellerProductId', 'sellerProductName', 'brand')


@admin.register(CoupangItemImage)
class CoupangItemImageAdmin(admin.ModelAdmin):
    """
    이미지 Admin (원한다면)
    """
    list_display = ('id', 'parent_item', 'imageOrder', 'imageType', 'cdnPath', 'vendorPath')
    search_fields = ('cdnPath', 'vendorPath')
