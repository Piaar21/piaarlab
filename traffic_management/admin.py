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
        'store_name',
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
    
    
from .models import Traffic

@admin.register(Traffic)
class TrafficAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'method', 'inflow_count', 'days', 'vendor', 'type', 'created_at', 'updated_at')
    list_filter = ('method', 'type', 'vendor')
    search_fields = ('name', 'vendor')
    
    
from .models import RankingMonitoring, KeywordRanking

class KeywordRankingInline(admin.TabularInline):
    model = KeywordRanking
    extra = 1  # 새 항목 추가 시 기본적으로 보여줄 인라인 폼 수

@admin.register(RankingMonitoring)
class RankingMonitoringAdmin(admin.ModelAdmin):
    list_display = ('product_id', 'product_name', 'product_url')
    search_fields = ('product_id', 'product_name')
    inlines = [KeywordRankingInline]

@admin.register(KeywordRanking)
class KeywordRankingAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'rank', 'ranking','update_at')
    search_fields = ('keyword',)
    list_filter = ('ranking',)

from .models import NaverMarketingCost

@admin.register(NaverMarketingCost)
class NaverMarketingCostAdmin(admin.ModelAdmin):
    list_display = ('task', 'date', 'cost', 'created_at')
    list_filter = ('task', 'date')
    search_fields = ('product__name',)  # product의 name 필드를 검색
    ordering = ('-date',)               # 최신 날짜가 상단에 오도록


from .models import Ad

@admin.register(Ad)
class AdAdmin(admin.ModelAdmin):
    # 리스트 화면에 표시할 필드
    list_display = (
        'id',
        'start_date',
        'end_date',
        'channel',
        'name',
        'category',    # 카테고리 필드 표시
        'product',
        'sales',
        'margin',
        'cost',
        'profit',      # @property 로 정의한 메서드도 표시 가능
        'margin_rate',
        'profit_rate',
        'roas',
        'roi',
    )
    # 사이드바에 필터로 표시할 필드
    list_filter = (
        'category',    # 카테고리별 필터
        'channel',
        'company',
        'start_date',
    )
    # 검색 가능한 필드
    search_fields = (
        'category',
        'name',
        'product',
        'company',
    )
    # 날짜 내비게이션
    date_hierarchy = 'start_date'
    # 기본 정렬
    ordering = ('-start_date',)
    # 페이지당 항목 수
    list_per_page = 25