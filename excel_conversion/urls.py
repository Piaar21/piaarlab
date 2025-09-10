# excel_conversion/urls.py
from django.urls import path
from . import views

app_name = 'excel_conversion'

urlpatterns = [
    path('upload/', views.excel_upload, name='excel_upload'),
    path('download/', views.excel_download, name='excel_download'),
    path('download/set', views.excel_download_settlement, name='excel_download_settlement'),
    path('clear/', views.excel_clear, name='excel_clear'),
    path('clear/set', views.excel_clear_set, name='excel_clear_set'),
    path('settlement/', views.excel_settlement, name='excel_settlement'),
    path('shipcode/', views.excel_shipcode, name='excel_shipcode'),
    path('clear/shipcode/set', views.excel_shipcode_clear_set, name='excel_shipcode_clear_set'),
]