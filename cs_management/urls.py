# cs_management/urls.py
from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static


app_name = 'cs_management'

urlpatterns = [
    path('chat/', views.chat_inquiry, name='chat_inquiry'),
    path('chat/rooms/', views.get_rooms_json, name='get_rooms_json'),
    path('chat/send-message/', views.chat_send_message, name='chat_send_message'),
    path('chat/navertalk/', views.naver_talk_callback, name='naver_talk_callback'),
    path('chat/<str:user_id>/', views.chat_inquiry_detail, name='chat_inquiry_detail'),
    path('chat/<str:user_id>/messages/', views.get_messages_json, name='get_messages_json'),
    
    
    path('product/', views.product_inquiry, name='product_inquiry'),
    path('customer-center/', views.customer_center_inquiry, name='customer_center_inquiry'),
]
