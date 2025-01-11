# webhook/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.webhook, name='webhook'),  # 예시로 "/webhook/"로 들어오는 요청 처리
]
