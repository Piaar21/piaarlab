# rankings/urls.py

from django.urls import path,include
from . import views


app_name = 'rankings'



urlpatterns = [
    path('', views.dashboard, name='home'),  # 대시보드 페이지로 연결되도록 수정
    path('product/add/', views.product_add, name='product_add'),
    path('product/list/', views.product_list, name='product_list'),
    path('product/bulk_edit/', views.product_bulk_edit, name='product_bulk_edit'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('issues/', views.issues, name='issues'),
    path('average-ranking/', views.average_ranking, name='average_ranking'),
    path('task/register/', views.task_register, name='task_register'),
    path('task/edit/', views.task_edit, name='task_edit'),
    path('task/update/', views.task_update, name='task_update'),
    path('product/delete/', views.product_delete, name='product_delete'),
    path('traffic/register/', views.traffic_register, name='traffic_register'),
    path('traffic/list/', views.traffic_list, name='traffic_list'),
    path('traffic/bulk_edit/', views.traffic_bulk_edit, name='traffic_bulk_edit'),
    path('completed-tasks/', views.completed_tasks_list, name='completed_tasks_list'),
    path('completed-tasks/delete/', views.completed_tasks_delete, name='completed_tasks_delete'),
    path('traffics/delete/', views.traffic_delete, name='traffic_delete'),
    path('task/action/', views.task_action, name='task_action'),
    path('task/extend/', views.task_extend, name='task_extend'),
    path('product/select/', views.product_select, name='product_select'),
    path('task/edit/<str:task_ids>/', views.task_edit, name='task_edit'),
    path('update_all_rankings/', views.update_all_rankings, name='update_all_rankings'),
    path('traffic/cost_summary/', views.traffic_cost_summary, name='traffic_cost_summary'),
    path('accounts/', include('allauth.urls')),
    path('products/', views.product_list_view, name='product_list'),
    path('products/create/', views.product_create_view, name='product_create'),
    path('my-page/', views.my_page, name='my_page'),
    path('ad_single_summary/', views.ad_single_summary, name='ad_single_summary'),
    path('ad/create/', views.ad_create, name='ad_create'),
    path('ad/<int:pk>/update/', views.ad_update, name='ad_update'),
    path('ad/bulk_edit/', views.ad_bulk_edit, name='ad_bulk_edit'),
    path('ad/<int:pk>/delete/', views.ad_delete, name='ad_delete'),
    path('ad/upload/', views.ad_upload, name='ad_upload'),
    path('ads/delete_multiple/', views.ad_delete_multiple, name='ad_delete_multiple'),
    path('ad/download_sample_excel/', views.download_sample_excel, name='download_sample_excel'),
    path('traffic/download_sample_excel/', views.download_traffic_sample_excel, name='download_traffic_sample_excel'),
    path('product/download-sample/', views.download_product_sample_excel, name='download_product_sample_excel'),
    path('api/get_ranking_data/', views.get_ranking_data, name='get_ranking_data'),
    path('task/reregister/', views.task_reregister, name='task_reregister'),  # 추가된 URL 패턴
    path('products/download-excel/', views.download_selected_products_excel, name='download_selected_products_excel'),
    path('tasks/upload-excel/', views.upload_excel_data, name='upload_excel_data'),
    path('tasks/register-from-excel/', views.task_register_from_excel, name='task_register_from_excel'),


]
