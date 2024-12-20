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
]
