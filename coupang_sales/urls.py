# coupang_sales/urls.py
from django.urls import path
from . import views  # views 모듈 임포트

urlpatterns = [
    path('group-management/', views.group_management_view, name='group_management'),
    path('product-list/', views.product_list_view, name='product_list'),
    path('update-coupang-products/', views.update_coupang_products, name='update_coupang_products'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('sales-report/', views.sales_report_view, name='sales_report'),
    path('ad-report/', views.ad_report_view, name='ad_report'),
    path('profit-loss/', views.profit_loss_view, name='profit_loss'),
]
