# excel_conversion/urls.py
from django.urls import path
from . import views

app_name = 'excel_conversion'

urlpatterns = [
    path('upload/', views.excel_upload, name='excel_upload'),
    path('download/', views.excel_download, name='excel_download'),
    path('clear/', views.excel_clear, name='excel_clear'),
    
]