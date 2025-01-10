# return_process/urls.py

from django.urls import path
from . import views
from .views import signup
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),  # 루트 URL 패턴 추가
    path('signup/', views.signup, name='signup'),  # 회원가입 URL 추가
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('returns/', views.return_list, name='반품목록'),
    path('scan/', views.scan, name='스캔'),
    path('scan/submit/', views.scan_submit, name='scan_submit'),
    path('collected/', views.collected_items, name='수거완료'),
    path('inspect/<int:item_id>/', views.inspect, name='검수'),
    path('inspected/', views.inspected_items, name='검수완료'),
    path('process_return/<int:item_id>/', views.process_return, name='반품처리'),
    path('returned/', views.returned_items, name='반품완료'),
    path('update_stock/<int:item_id>/', views.update_stock, name='재고반영'),
    path('stock_updated/', views.stock_updated_items, name='재고반영완료'),
    path('completed/', views.completed_items, name='처리완료'),
    path('process_return_bulk/', views.process_return_bulk, name='반품처리_bulk'),
    path('update_stock_bulk/', views.update_stock_bulk, name='재고반영_bulk'),
    path('update_complete_bulk/', views.update_complete_bulk, name='처리완료_bulk'),
    path('update_returns/', views.update_returns, name='update_returns'),
    path('download_unmatched/', views.download_unmatched, name='download_unmatched'),  # 추가
    path('upload_returns_excel/', views.upload_returns_excel, name='upload_returns_excel'),
    path('upload_courier_excel/', views.upload_courier_excel, name='upload_courier_excel'),
    path('finalize_excel_import/', views.finalize_excel_import, name='finalize_excel_import'),
    path('upload_reason_excel/', views.upload_reason_excel, name='upload_reason_excel'),
    path('send_shipping_sms/', views.send_shipping_sms, name='send_shipping_sms'),
    path('delete_return_item/', views.delete_return_item, name='delete_return_item'),
    path('scan/check_number/', views.check_number_submit, name='check_number_submit'),
    path('returned/download/', views.download_returned_items, name='download_returned_items'),  # 추가
    path('return_dashboard/', views.return_dashboard, name='return_dashboard'),
    path('update-claim-type/', views.update_claim_type_bulk, name='update_claim_type'),

]
