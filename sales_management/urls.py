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
    path('deleted-coupang-sales/', views.deleted_coupang_sales_view, name='deleted_coupang_sales'),
    path('ad-report/', views.ad_report_view, name='ad_report'),
    path('ad-report/update/', views.update_ads_report, name='update_ads_report'),
    path('ad-report/delete/', views.delete_ads_report, name='delete_ads_report'),
    path('sales/upload-ads-excel/', views.upload_ads_excel_view, name='upload_ads_excel'),
    path('sales/update-coupang-sales/', views.update_coupang_sales_view, name='update_coupang_sales'),
    path('profit-report/', views.profit_report_view, name='profit_report'),
    path('profit-report/update/cost', views.update_costs_from_seller_tool_view, name='update_cost_profit_report'),

    # path('naver-group-management/', views.naver_group_management_view, name='naver_group_management'),
    path('naver-product-list/', views.naver_product_list_view, name='naver_product_list'),
    path('naver-update-products/', views.naver_update_products, name='naver_update_products'),
    # path('naver-delete-all-data/', views.naver_delete_all_data, name='naver_delete_all_data'),
    # path('naver-dashboard/', views.naver_dashboard_view, name='naver_dashboard'),
    path('naver-sales-report/', views.naver_sales_report_view, name='naver_sales_report'),
    # path('naver-sales/upload-excel/', views.naver_upload_excel_view, name='naver_upload_excel'),
    path('naver-update-sales/', views.naver_update_sales_view, name='naver_update_sales'),
    path('naver-delete-sales/', views.deleted_naver_sales, name='naver_delete_sales'),
    path('naver-ad-report/', views.naver_ad_report_view, name='naver_ad_report'),
    path('naver-ad-report/update/', views.naver_update_ads_report, name='naver_update_ads_report'),
    # path('naver-sales/upload-ads-excel/', views.naver_upload_ads_excel_view, name='naver_upload_ads_excel'),
    # path('naver-sales/update-sales/', views.naver_update_sales_view, name='naver_update_sales'),
    path('naver-profit-report/', views.naver_profit_report_view, name='naver_profit_report'),
    # path('naver-profit-report/update/cost', views.naver_update_costs_from_seller_tool_view, name='naver_update_cost_profit_report'),
]
