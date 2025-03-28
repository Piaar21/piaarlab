"""
URL configuration for piaarlab project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('return_process.urls')),  # 루트 URL에 return_process.urls 포함
    path('delayed/', include('delayed_management.urls')),  # /delayed/ 경로에 delayed_management.urls 포함
    path('cs/', include('cs_management.urls')),    # /cs/ 경로에 cs_management.urls 포함
    path('webhook/', include('webhook.urls')),  # 새로 추가
    path('sales/', include('sales_management.urls')),  
    path('traffic/', include('traffic_management.urls')),  
    
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)