# cs_management/urls.py

from django.urls import path
from . import views  # 같은 앱 내 views.py import
from django.conf import settings
from django.conf.urls.static import static

app_name = 'cs_management'

urlpatterns = [
    # inquiry_product 뷰 연결
    path('inquiries/product/', views.inquiry_product_list, name='inquiry_product_list'),
    path('inquiries/update/', views.update_inquiries, name='update_inquiries'),
    path('inquiries/delete-all/', views.delete_all_inquiries, name='delete_all_inquiries'),
    path('inquiries/answer/', views.answer_inquiry_unified, name='answer_inquiry_unified'),
    path('inquiries/webhook/', views.send_inquiry_webhook_view, name='send_inquiry_webhook'),

    
    path('inquiries/<int:inquiry_id>/save-answer/', views.inquiry_save_answer, name='inquiry_save_answer'),
    path('inquiries/<int:inquiry_id>/gpt-recommend/',views.inquiry_gpt_recommend,name='inquiry_gpt_recommend'),
    path('inquiries/answer-unified/', views.answer_inquiry_unified, name='answer_inquiry_unified'),

    # 새 플랫폼센터 문의 업데이트
    path('inquiries/center/update/', views.update_center_inquiries, name='update_center_inquiries'),
    path('inquiries/center/', views.inquiry_center_list, name='inquiry_center_list'),
    path('inquiries/delete-all/center/', views.delete_all_inquiries_center, name='delete_all_inquiries_center'),
    path('inquiries/center/answer-unified/', views.answer_center_inquiry_unified, name='answer_center_inquiry_unified'),
]

# DEBUG 모드일 때 미디어 파일 서빙 (이미지, 첨부파일 등)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
