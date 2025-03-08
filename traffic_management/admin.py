from django.contrib import admin
from .models import Task, Product, Keyword, Traffic

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        'id', 
        'product_name', 
        'category', 
        'keyword', 
        'url', 
        'current_rank', 
        'difference_rank', 
        'is_completed', 
        'traffic', 
        'created_at',
        'available_start_date',
        'available_end_date',
        'original_link',
        'original_mid',
        'single_product_link',
        'single_product_mid',
    )
    list_filter = (
        'category', 
        'is_completed', 
        'traffic', 
        'is_extended', 
        'available_start_date', 
        'available_end_date'
    )
    search_fields = (
        'product_name', 
        'category', 
        'keyword__name', 
        'url', 
        'memo'
    )
    ordering = ('-created_at',)


from django.contrib import admin
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'store_name', 'manager',
                    'single_product_link',
'single_product_mid',
'original_link',

'original_mid')
    search_fields = ('name', 'search_keyword', 'store_name', 'manager')
    list_filter = ('category', 'store_name')