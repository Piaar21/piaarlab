from django.contrib import admin
from .models import CoupangProduct, CoupangItem, CoupangItemImage, CoupangDailySales,AdsReport, CoupangAdsReport,PurchaseCost

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
    list_display = ('id', 'sellerProductId', 'productId','sellerProductName', 'brand', 'statusName')
    search_fields = ('sellerProductId', 'sellerProductName', 'brand')


@admin.register(CoupangItemImage)
class CoupangItemImageAdmin(admin.ModelAdmin):
    """
    이미지 Admin (원한다면)
    """
    list_display = ('id', 'parent_item', 'imageOrder', 'imageType', 'cdnPath', 'vendorPath')
    search_fields = ('cdnPath', 'vendorPath')


class CoupangDailySalesAdmin(admin.ModelAdmin):
    list_display = (
        'displayed_product_id',
        'sku_id',
        'item_name',
        'product_name',
        'option_name',
        'delivery_label',
        'category_name',
        'item_winner_ratio',
        'net_sales_amount',
        'net_sold_items',
        'total_transaction_amount',
        'total_transaction_items',
        'total_cancellation_amount',
        'total_cancelled_items',
        'immediate_cancellation_items',
        'date',
    )
    search_fields = ('displayed_product_id', 'sku_id', 'item_name', 'category_name')
    list_filter = ('date', 'category_name')
    ordering = ('-date',)

admin.site.register(CoupangDailySales, CoupangDailySalesAdmin)


@admin.register(AdsReport)
class AdsReportAdmin(admin.ModelAdmin):
    """
    AdsReport 모델(Admin)
    """
    list_display = (
        "report_date",
        "delivery_label",
        "sold_items",
        "ads_sold_items",
        "conversion_rate",
        "total_transaction_amount",
        "ads_total_transaction_amount",
        "ad_spend",
        "net_sales_amount",
        "product_name",
        "option_name",
        "item_name",
        "sku_id",
        "external_vendor_sku",
        "item_id",
    )
    list_filter = ("report_date", "delivery_label")
    search_fields = ("product_name", "option_name", "item_name", "sku_id")

@admin.register(CoupangAdsReport)
class CoupangAdsReportAdmin(admin.ModelAdmin):
    """
    CoupangAdsReport 모델(Admin)
    """
    list_display = (
        "date",
        "ad_type",
        "campaign_id",
        "campaign_name",
        "ad_group",
        "executed_product_name",
        "executed_option_id",
        "converting_product_name",
        "converting_option_id",
        "ad_placement",
        "impressions",
        "clicks",
        "ad_spend",
        "ctr",
        "orders",
        "sold_quantity",
        "sales_amount",
        "roas",
    )
    list_filter = ("date", "ad_type", "campaign_id")
    search_fields = (
        "campaign_name",
        "ad_group",
        "executed_product_name",
        "converting_product_name",
    )

@admin.register(PurchaseCost)
class PurchaseCostAdmin(admin.ModelAdmin):
    """
    PurchaseCost 모델용 Admin 설정
    """
    list_display = ('id', 'sku_id', 'option_code', 'manager', 'purchasing_price')
    list_filter = ('manager',)
    search_fields = ('sku_id', 'option_code', 'manager')
    ordering = ('-id',)

from .models import NaverDailySales,naverItem

@admin.register(naverItem)
class naverItemAdmin(admin.ModelAdmin):
    list_display = (
        'productID',
        'channelProductID',
        'skuID',
        'itemName',
        'option_name',
        'product_price',
        'option_price',
        'sale_price',
        'profit',
        'account_name',
    )
    search_fields = (
        'productID',
        'channelProductID',
        'skuID',
        'itemName',
        'option_name',
        'account_name',
    )
    list_filter = ('account_name',)


@admin.register(NaverDailySales)
class NaverDailySalesAdmin(admin.ModelAdmin):
    # 1) 리스트 화면에 표시할 컬럼
    list_display = (
        "date",
        "store",
        "order_ID",
        "product_name",
        "option_name",
        "sales_qty",
        "sales_revenue",
        "refunded_qty",
        "refunded_revenue",
        "product_id",
        "originalProductId",
        "option_id",
    )

    # 2) 검색 박스에서 검색할 필드 (부분 일치)
    search_fields = (
        "order_ID",
        "product_name",
        "option_name",
        "store",
        "product_id",
        "originalProductId",
        "option_id",
    )

    # 3) 필터 사이드바
    list_filter = (
        "store",
        "date",
    )

    # 4) 정렬 기준 (예시: 날짜 최신순 정렬)
    ordering = ("-date",)
    
    # (선택) 한 페이지에 표시할 목록 개수
    list_per_page = 50    


from django.contrib import admin
from .models import NaverAdReport
from django.db.models import Sum

@admin.register(NaverAdReport)
class NaverAdReportAdmin(admin.ModelAdmin):
    list_display = (
        'date', 
        'ad_group_id', 
        'ad_id', 
        'customer_id', 
        'impression', 
        'click', 
        'cost', 
        'conversion_count', 
        'sales_by_conversion', 
        'ctr', 
        'roas',
    )
    search_fields = ('ad_id', 'ad_group_id', 'customer_id')
    list_filter = ('date',)
    # date_hierarchy 옵션을 추가하면 상단에 날짜별 드롭다운이 표시됩니다.
    date_hierarchy = 'date'

    def changelist_view(self, request, extra_context=None):
        # 기본 ChangeList 결과를 가져옵니다.
        response = super().changelist_view(request, extra_context)
        try:
            qs = response.context_data['cl'].queryset
        except (AttributeError, KeyError):
            return response

        # 예시로 cost와 sales_by_conversion의 총합 집계
        aggregate = qs.aggregate(
            total_cost=Sum('cost'),
            total_sales_by_conversion=Sum('sales_by_conversion'),
        )
        # 집계 결과를 추가 컨텍스트에 넣습니다.
        response.context_data['aggregate'] = aggregate
        return response


from .models import NaverAdShoppingProduct

@admin.register(NaverAdShoppingProduct)
class NaverAdShoppingProductAdmin(admin.ModelAdmin):
    list_display = ('date', 'ad_group_id', 'ad_id', 'product_id', 'product_id_of_mall', 'product_name', 'product_image_url','category_path')
    search_fields = ('ad_id', 'product_name','product_id_of_mall')



from .models import NaverPurchaseCost

@admin.register(NaverPurchaseCost)
class NaverPurchaseCostAdmin(admin.ModelAdmin):
    list_display = ('sku_id', 'option_code', 'manager', 'purchasing_price')
    search_fields = ('sku_id', 'option_code', 'manager')
    list_filter = ('manager',)
    ordering = ('sku_id',)



