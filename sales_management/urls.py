# sales_management/urls.py
from django.urls import path
from . import views  # views 모듈 임포트



urlpatterns = [
    path('group-management/', views.group_management_view, name='group_management'),
    path('product-list/', views.product_list_view, name='product_list'),
    path('update-coupang-products/', views.update_coupang_products, name='update_coupang_products'),
    path('delete-all-data/', views.delete_all_coupang_data, name='delete_all_coupang_data'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('sales-report/', views.sales_report_view, name='sales_report'),
    path('sales/upload-excel/', views.upload_excel_view, name='upload_excel'),
    path('update-coupang-sales/', views.update_coupang_sales_view, name='update_coupang_sales'),
    path('ad-report/', views.ad_report_view, name='ad_report'),
    path('ad-report/update/', views.update_ads_report, name='update_ads_report'),
    path('sales/upload-ads-excel/', views.upload_ads_excel_view, name='upload_ads_excel'),
    path('sales/update-coupang-sales/', views.update_coupang_sales_view, name='update_coupang_sales'),
    path('profit-report/', views.profit_report_view, name='profit_report'),
    path('profit-report/update/cost', views.update_costs_from_seller_tool_view, name='update_cost_profit_report'),
]
