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

    path('inquiries/center/', views.inquiry_center_list, name='inquiry_center_list'),
    path('inquiries/generate-gpt/', views.generate_gpt_summaries, name='generate_gpt_summaries'),
]

# DEBUG 모드일 때 미디어 파일 서빙 (이미지, 첨부파일 등)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
