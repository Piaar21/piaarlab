# return_process/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser
from .models import NaverAccount, CoupangAccount

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('email', 'name', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active')
    search_fields = ('email',)
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password', 'name')}),
        ('권한', {'fields': ('is_staff', 'is_active', 'is_superuser', 'groups', 'user_permissions')}),
    )

admin.site.register(CustomUser, CustomUserAdmin)

admin.site.register(NaverAccount)
admin.site.register(CoupangAccount)


# return_process/admin.py

from django.contrib import admin
from .models import ReturnItem

@admin.register(ReturnItem)
class ReturnItemAdmin(admin.ModelAdmin):
    list_display = (
        'order_number', 'platform', 'store_name', 'product_name', 'quantity',
        'processing_status', 'collected_at', 'inspected_at', 'returned_at',
        'stock_updated_at', 'completed_at','claim_type',
    )
    list_filter = ('platform', 'store_name', 'processing_status', 'claim_type')
    search_fields = ('order_number', 'product_name', 'store_name', 'option_code','processing_status')
    ordering = ('-last_update_date',)
    
    # readonly_fields: 관리자가 자동으로 기록되는 날짜필드를 수정하지 못하도록 설정
    readonly_fields = ('last_update_date', 'collected_at', 'inspected_at', 'returned_at', 'stock_updated_at', 'completed_at')
    
    # 상세 페이지에서 필드 그룹화(옵션)
    fieldsets = (
        (None, {
            'fields': ('platform', 'order_number', 'store_name', 'product_name', 'option_name', 'quantity')
        }),
        ('클레임 정보', {
            'fields': ('claim_type', 'claim_status', 'claim_reason', 'customer_reason')
        }),
        ('배송 정보', {
            'fields': ('invoice_number', 'return_shipping_charge', 'shipping_charge_payment_method', 'collect_tracking_number', 'collect_delivery_company')
        }),
        ('상태 정보', {
            'fields': ('processing_status', 'note', 'inspector', 'product_issue')
        }),
        ('날짜 정보', {
            'fields': ('delivered_date', 'claim_request_date', 'last_update_date', 'collected_at', 'inspected_at', 'returned_at', 'stock_updated_at', 'completed_at')
        }),
        ('추가 정보', {
            'fields': ('seller_product_item_id', 'recipient_name', 'recipient_contact')
        }),
    )
