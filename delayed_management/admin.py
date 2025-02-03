# delayed_management/admin.py

from django.contrib import admin
from .models import (
    ExternalProductItem,
    ExternalProductOption,
    OptionMapping,
    OptionPlatformDetail,
    DelayedShipment,
    OutOfStock,
)

## 1) ExternalProductOption: Inline
class ExternalProductOptionInline(admin.TabularInline):
    model = ExternalProductOption
    extra = 0  # 기본 추가 폼 X (필요 시 변경 가능)

@admin.register(ExternalProductItem)
class ExternalProductItemAdmin(admin.ModelAdmin):
    """
    네이버 상품(원상품) 모델
    - Inline: ExternalProductOption
    - list_display: 모든(혹은 주요) 필드
    """
    inlines = [ExternalProductOptionInline]

    list_display = (
        "id",                    
        "origin_product_no",
        "product_name",
        "representative_image",
        "sale_price",
        "stock_quantity",
        "seller_code_info",
        "updated_at",
    )
    search_fields = (
        "product_name",
        "origin_product_no",
        "seller_code_info",
    )


@admin.register(ExternalProductOption)
class ExternalProductOptionAdmin(admin.ModelAdmin):
    """
    ExternalProductOption 모델을 독립적으로도 표시
    """
    list_display = (
        "id",
        "product",  # FK
        "option_id",
        "option_name1",
        "option_name2",
        "stock_quantity",
        "price",
        "seller_manager_code",
        "seller_tool_stock",   # ★ 추가 표시
        "store_name",          # ★ 추가 표시
    )
    search_fields = (
        "option_id",
        "option_name1",
        "option_name2",
        "seller_manager_code",
        "store_name",
    )


## 2) OptionPlatformDetail: Inline
class OptionPlatformDetailInline(admin.TabularInline):
    model = OptionPlatformDetail
    extra = 0

@admin.register(OptionMapping)
class OptionMappingAdmin(admin.ModelAdmin):
    """
    내부 옵션코드(우리 고유 option_code) 중심
    - Inline: OptionPlatformDetail
    - list_display: 모든(혹은 주요) 필드
    """
    inlines = [OptionPlatformDetailInline]

    list_display = (
        "id",
        "option_code",
        "order_product_name",
        "order_option_name",
        "store_name",
        "seller_product_name",
        "seller_option_name",
        "expected_date",
        "expected_start",
        "expected_end",
        # ★ 추가
        "base_sale_price",
        "discounted_price",
        "updated_at",
    )
    search_fields = (
        "option_code",
        "order_product_name",
        "order_option_name",
        "store_name",
        "seller_product_name",
        "seller_option_name",
    )


@admin.register(OptionPlatformDetail)
class OptionPlatformDetailAdmin(admin.ModelAdmin):
    """
    플랫폼별 상세정보 (OptionMapping과 1:N)
    - list_display: 모든 필드
    - search_fields: 필요한 필드
    """
    list_display = (
        "id",
        "option_mapping",       
        "platform_name",
        "platform_product_id",
        "platform_option_id",
        "order_product_name",
        "order_option_name",
        "stock",
        "price",
        "seller_manager_code",
        "representative_image",
        "origin_product_no",
        "updated_at",
        "seller_tool_stock",   # 이미 포함되어 있다면 생략
        "out_of_stock_at",
    )
    search_fields = (
        "platform_name",
        "platform_product_id",
        "platform_option_id",
        "order_product_name",
        "order_option_name",
        "seller_manager_code",
        "origin_product_no",
        "option_mapping__option_code",  # FK를 통한 검색
    )


@admin.register(DelayedShipment)
class DelayedShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'order_number_1',
        'option_code',
        'store_name',
        'customer_name',
        'status',
        'send_status',
        'token',  
    )
    list_filter = ('status', 'send_status', 'store_name')
    search_fields = ('order_number_1', 'option_code', 'customer_name', 'token')


@admin.register(OutOfStock)
class OutOfStockAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'platform_name',
        # 'representative_image',
        'product_id',
        'option_id',
        'option_id_stock',
        'order_product_name',
        'order_option_name_01',
        'order_option_name_02',
        'option_code',
        'original_price',
        'sale_price',
        'add_option_price',
        'out_of_stock_at',
        'updated_at',
    )
    list_filter = ('platform_name',)  # 필요 시 다른 필드 추가
    search_fields = (
        'platform_name',          # 플랫폼명으로 검색
        'option_code',            # 옵션코드로 검색
        'product_id',
        'option_id',
        'order_product_name',
        'order_option_name_01',
        'order_option_name_02',
    )
    ordering = ('-id',)