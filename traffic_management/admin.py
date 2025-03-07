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