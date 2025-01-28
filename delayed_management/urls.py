# delayed_management/urls.py
from django.urls import path
from . import views  # views 모듈 자체 임포트

urlpatterns = [
    path('upload-delayed-orders/', views.upload_delayed_orders, name='upload_delayed_orders'),
    path('upload-store-mapping/', views.upload_store_mapping, name='upload_store_mapping'),
    path('delete-store-mapping/<int:mapping_id>/', views.delete_store_mapping, name='delete_store_mapping'),
    path('add-or-update-store-mapping/', views.add_or_update_store_mapping, name='add_or_update_store_mapping'),
    path('delayed-shipment-list/', views.delayed_shipment_list, name='delayed_shipment_list'),
    path('change-exchangeable-options/', views.change_exchangeable_options, name='change_exchangeable_options'),
    path('restock-management/', views.restock_list, name='restock_management'),
    path('update-restock/', views.update_restock_from_sheet, name='update_restock_from_sheet'),
    path('send-message-list/', views.send_message_list, name='send_message_list'),
    path('send-message-process/', views.send_message_process, name='send_message_process'),
    path('customer-action/', views.customer_action_view, name='customer_action'),
    path('option-change/', views.option_change_view, name='option_change_view'),
    path('option-change-process/', views.option_change_process, name='option_change_process'),
    path('thank-you/', views.thank_you_view, name='thank_you_view'),
    path('option-change-done/', views.option_change_done, name='option_change_done'),
    path('process-confirmed-shipments/', views.process_confirmed_shipments, name='process_confirmed_shipments'),
        # 출고완료 목록 페이지
    path('shipped-list/', views.shipped_list_view, name='shipped_list'),
    path('shipped/process/', views.process_shipped_shipments, name='process_shipped_shipments'),

    # 출고완료 처리 POST 액션
    path('process-shipped/', views.process_shipped_shipments, name='process_shipped_shipments'),
    path('confirmed-list/', views.confirmed_list, name='confirmed_list'),

    path('api/exchange-options/<int:shipment_id>/', views.get_exchange_options_api, name='get_exchange_options_api'),
    path('exchange-options/<int:shipment_id>/remove/', views.remove_exchange_option_api, name='remove_exchange_option_api'),
    path('exchange-options/<int:shipment_id>/add/', views.add_exchange_option_api, name='add_exchange_option_api'),
    path('api/sellertool-options/<int:shipment_id>/', views.get_seller_tool_options_api, name='get_seller_tool_options_api'),
    path('api/sellertool-options/<int:shipment_id>/', views.get_seller_tool_options_api, name='get_seller_tool_options_api'),
    path('api/save-sellertool-options/<int:shipment_id>/', views.save_seller_tool_options_api, name='save_seller_tool_options_api'),
    path('out-of-stock-management/', views.out_of_stock_management_view, name='out_of_stock_management'),
    # path('option-mapping/', views.option_mapping, name='option_mapping'),
    
    # path('option-mapping/add-or-update/', views.add_or_update_option_mapping, name='add_or_update_option_mapping'),
    # path('option-mapping/action/', views.action_option_mapping, name='action_option_mapping'),
    
    path('match-option-ids/', views.match_option_ids_view, name='match_option_ids'),
    path('out-of-stock-delete-all/', views.out_of_stock_delete_all_view, name='out_of_stock_delete_all'),
    path('option-id-stock-update/', views.option_id_stock_update_view, name='option_id_stock_update'),
    path('do-out-of-stock/', views.do_out_of_stock_view, name='do_out_of_stock'),
    path('add-stock-for-selection/', views.add_stock_9999_view, name='add_stock_9999'),
    path('update-seller-tool/', views.update_seller_tool_and_increase_stock_view, name='update_seller_tool'),
    # (1) 셀러툴 옵션 목록 (GET) - bulk
    path("out-of-stock/update-seller-tool-stock/", views.update_seller_tool_stock, name="update_seller_tool_stock"),
    path('solapi/webhook-message/', views.solapi_webhook_message, name='solapi_webhook_message'),
    path('download-outofstock-excel-today/', views.download_out_of_stock_excel_today, name='download_out_of_stock_excel_today'),


    # path('api-option-list/', views.api_option_list_view, name='api_option_list'),
    path('api-option-list/', views.outofstock_list_view, name='api_option_list'),
    # path('update-naver-product-list/', views.update_naver_product_list, name='update_naver_product_list'),
    # path('update-coupang-product-list/', views.update_coupang_product_list, name='update_coupang_product_list'),
    path('update-naver-option-list/', views.update_naver_option_list, name='update_naver_option_list'),
    path('update-coupang-option-list/', views.update_coupang_option_list, name='update_coupang_option_list'),
        path('coupang-product-check/', views.coupang_product_check_view, name='coupang_product_check_view'),

]

