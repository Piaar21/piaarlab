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
]
