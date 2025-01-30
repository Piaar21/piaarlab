# cs_management/admin.py

from django.contrib import admin
from .models import Inquiry, CoupangOrderSheet

@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    """
    모든 필드를 한 눈에 보기 위해 list_display에 전부 열거.
    실제로는 화면이 너무 길어질 수 있으니 적절히 조정하세요.
    """
    list_display = (
        'id',
        'platform',
        'store_name',
        'inquiry_id',
        'product_id',
        'product_name',
        'content',
        'author',
        'created_at_utc',
        'answered',
        'answer_content',
        'representative_image',
        'answer_date',
        'gpt_summary',
        'order_ids',
        'raw_json',   # JSONField
        'created_at',
        'updated_at',
        'answered_at',
        'answer_updated_at',
    )
    # 검색/필터 예시
    search_fields = ('platform', 'store_name', 'inquiry_id', 'author', 'content')
    list_filter = ('platform', 'answered', 'created_at_utc')

@admin.register(CoupangOrderSheet)
class CoupangOrderSheetAdmin(admin.ModelAdmin):
    """
    모든 필드를 list_display에 표시 예시
    """
    list_display = (
        'shipment_box_id',
        'order_id',
        'ordered_at',
        'paid_at',
        'status',
        'shipping_price',
        'remote_price',
        'remote_area',
        'parcel_print_message',
        'split_shipping',
        'able_split_shipping',
        'orderer_name',
        'orderer_safenum',
        'receiver_name',
        'receiver_safenum',
        'receiver_addr1',
        'receiver_addr2',
        'receiver_postcode',
        'delivery_company_name',
        'invoice_number',
        'in_transit_datetime',
        'delivered_date',
        'refer',
        'shipment_type',
        'order_items',       # JSONField
        'representative_image',
        'answer_date',
        'gpt_summary',
        'raw_json',          # JSONField
        'created_at',
        'updated_at',
    )
    # 검색/필터 예시
    search_fields = ('order_id', 'shipment_box_id', 'receiver_name', 'receiver_addr1', 'orderer_name')
    list_filter = ('status', 'remote_area', 'split_shipping', 'able_split_shipping', 'created_at')
