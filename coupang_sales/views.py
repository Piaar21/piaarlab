# coupang_sales/views.py
from django.shortcuts import render
from django.http import JsonResponse
import logging
# api_clients.py에서 정의한 COUPANG_ACCOUNTS, fetch_coupang_seller_product 불러오기
from .api_clients import COUPANG_ACCOUNTS
from .models import CoupangItemList, CoupangItem, CoupangItemImage

logger = logging.getLogger(__name__)


def group_management_view(request):
    return render(request, 'coupang_sales/group_management.html')

# 상품리스트 시작

def product_list_view(request):
    return render(request, 'coupang_sales/product_list.html')


def dashboard_view(request):
    return render(request, 'coupang_sales/dashboard.html')

def sales_report_view(request):
    return render(request, 'coupang_sales/sales_report.html')

def ad_report_view(request):
    return render(request, 'coupang_sales/ad_report.html')

def profit_loss_view(request):
    return render(request, 'coupang_sales/profit_loss.html')
