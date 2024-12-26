# delayed_management/urls.py
from django.urls import path
from . import views  # views 모듈 자체 임포트

urlpatterns = [
    path('upload-delayed-orders/', views.upload_delayed_orders, name='upload_delayed_orders'),
    path('upload-file/', views.upload_file_view, name='upload_file'),
    path('post-list/', views.post_list_view, name='post_list'),
    path('upload-store-mapping/', views.upload_store_mapping, name='upload_store_mapping'),
    path('delete-store-mapping/<int:mapping_id>/', views.delete_store_mapping, name='delete_store_mapping'),
    path('add-or-update-store-mapping/', views.add_or_update_store_mapping, name='add_or_update_store_mapping'),
    path('delayed-shipment-list/', views.delayed_shipment_list, name='delayed_shipment_list'),
    path('delete-delayed-shipment/<int:shipment_id>/', views.delete_delayed_shipment, name='delete_delayed_shipment'),
    path('change-exchangeable-options/', views.change_exchangeable_options, name='change_exchangeable_options'),
    path('restock-management/', views.restock_list, name='restock_management'),
    path('restock-management/update/', views.restock_update, name='restock_update'),
    path('update-restock/', views.update_restock_from_sheet, name='update_restock_from_sheet'),
    path('map-stores-for-shipments/', views.map_stores_for_shipments, name='map_stores_for_shipments'),
    path('send-message-list/', views.send_message_list, name='send_message_list'),
    path('send-message-process/', views.send_message_process, name='send_message_process'),
    path('customer-action/', views.customer_action_view, name='customer_action'),
    path('option-change/', views.option_change_view, name='option_change_view'),
    path('option-change-process/', views.option_change_process, name='option_change_process'),
    path('thank-you/', views.thank_you_view, name='thank_you_view'),
    path('option-change-done/', views.option_change_done, name='option_change_done'),
    path('delayed/process-confirmed-shipments/', views.process_confirmed_shipments, name='process_confirmed_shipments'),
        # 출고완료 목록 페이지
    path('delayed/shipped-list/', views.shipped_list_view, name='shipped_list'),

    # 출고완료 처리 POST 액션
    path('delayed/process-shipped/', views.process_shipped_shipments, name='process_shipped_shipments'),
    path('delayed/confirmed-list/', views.confirmed_list, name='confirmed_list'),


]
