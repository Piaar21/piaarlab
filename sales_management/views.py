# sales_management/views.py
import requests
from datetime import date, timedelta, datetime
from django.db.models import Sum, Avg, F,Q
from collections import defaultdict, OrderedDict
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.http import JsonResponse
import logging
from django.utils import timezone
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import CoupangProduct, CoupangItem,CoupangDailySales,CoupangAdsReport,PurchaseCost
import json
from django.contrib import messages
from django.core.management import call_command
from django.views.decorators.http import require_POST
import os
import re
import pandas as pd
from django.conf import settings
import decimal
from decimal import Decimal


from .api_clients import COUPANG_ACCOUNTS, fetch_coupang_all_seller_products, get_coupang_seller_product,fetch_seller_tool_option_info

logger = logging.getLogger("sales_management")  # 로거 이름 일치

def group_management_view(request):
    return render(request, 'sales_management/group_management.html')

# 상품리스트 시작


def product_list_view(request):
    """
    1) 검색/필터 (로켓/마켓/검색어)
    2) 기존 로직 (delivery_label, fee 계산, grouped_data 등)
    3) context로 전달
    """
    from django.db.models import Q
    search_query = request.GET.get('search_query', '').strip()
    delivery_filter = request.GET.get('delivery_filter', '').strip()

    # 1) 기본 쿼리셋
    qs = CoupangProduct.objects.all().prefetch_related('items')

    # 2) 구분(delivery_filter) 로켓/마켓 필터
    if delivery_filter == 'rocket':
        # 로켓그로스 → 옵션 중 rocket_vendor_item_id가 null이 아닌 상품
        qs = qs.filter(items__rocket_vendor_item_id__isnull=False).distinct()
    elif delivery_filter == 'market':
        # 판매자배송 → 옵션 중 marketplace_vendor_item_id가 null이 아닌 상품
        qs = qs.filter(items__marketplace_vendor_item_id__isnull=False).distinct()

    # 3) 검색(search_query): 상품ID, SKU ID, custom ID, 상품명, 옵션명 등등
    if search_query:
        qs = qs.filter(
            Q(sellerProductId__icontains=search_query)
            | Q(sellerProductName__icontains=search_query)
            | Q(items__rocket_vendor_item_id__icontains=search_query)
            | Q(items__marketplace_vendor_item_id__icontains=search_query)
            | Q(items__rocket_external_vendor_sku__icontains=search_query)
            | Q(items__marketplace_external_vendor_sku__icontains=search_query)
            | Q(items__itemName__icontains=search_query)
        ).distinct()

    # 필터 적용 후의 상품 목록
    products = qs

    # (A) 전체 상품 개수
    total_count = products.count()

    # -----------------------------
    # (B) “기존 코드”
    # -----------------------------

    # 1) 상품 단위: 로켓&판매자 / 로켓그로스 / 판매자배송
    #    각 item도 "로켓그로스"/"판매자배송"/"-"
    for product in products:
        rocket_exists = False
        market_exists = False

        for item in product.items.all():
            if item.rocket_vendor_item_id:
                rocket_exists = True
            if item.marketplace_vendor_item_id:
                market_exists = True

        if rocket_exists and market_exists:
            product.delivery_label = "로켓&판매자"
        elif rocket_exists:
            product.delivery_label = "로켓그로스"
        else:
            product.delivery_label = "판매자배송"

        # 각 item에 대한 구분
        for item in product.items.all():
            if item.rocket_vendor_item_id:
                item.delivery_label = "로켓그로스"
            elif item.marketplace_vendor_item_id:
                item.delivery_label = "판매자배송"
            else:
                item.delivery_label = "-"


    # 2) grouped_data: [상품ID → { product, items }]
    grouped_data = {}
    for prod in products:
        spid = prod.sellerProductId
        if spid not in grouped_data:
            grouped_data[spid] = {
                'product': prod,
                'items': prod.items.all()
            }

    # 3) 계산 로직(수수료, salePrice/originalPrice 등)
    fee_rate = 0.1188

    for product in products:
        # (a) 상위행: 첫 번째 item 기준
        first_item = product.items.first()
        if first_item:
            if first_item.rocket_sale_price and first_item.rocket_sale_price > 0:
                top_sale_price = first_item.rocket_sale_price
            elif first_item.marketplace_sale_price and first_item.marketplace_sale_price > 0:
                top_sale_price = first_item.marketplace_sale_price
            else:
                top_sale_price = 0

            if first_item.rocket_original_price and first_item.rocket_original_price > 0:
                top_original_price = first_item.rocket_original_price
            elif first_item.marketplace_original_price and first_item.marketplace_original_price > 0:
                top_original_price = first_item.marketplace_original_price
            else:
                top_original_price = 0

            top_fee = top_sale_price * fee_rate if top_sale_price > 0 else 0
            top_profit = top_sale_price - top_fee if top_sale_price > 0 else 0

            product.top_sale_price = top_sale_price
            product.top_original_price = top_original_price
            product.top_fee = top_fee
            product.top_profit = top_profit
        else:
            product.top_sale_price = 0
            product.top_original_price = 0
            product.top_fee = 0
            product.top_profit = 0

        # (b) 하위행(옵션) 계산
        for item in product.items.all():
            if item.rocket_sale_price and item.rocket_sale_price > 0:
                i_sale_price = item.rocket_sale_price
            elif item.marketplace_sale_price and item.marketplace_sale_price > 0:
                i_sale_price = item.marketplace_sale_price
            else:
                i_sale_price = 0

            if item.rocket_original_price and item.rocket_original_price > 0:
                i_original_price = item.rocket_original_price
            elif item.marketplace_original_price and item.marketplace_original_price > 0:
                i_original_price = item.marketplace_original_price
            else:
                i_original_price = 0

            i_fee = i_sale_price * fee_rate if i_sale_price > 0 else 0
            i_profit = i_sale_price - i_fee if i_sale_price > 0 else 0

            # 템플릿에서 그대로 활용 가능하도록 계산된 값 저장
            item.calc_sale_price = i_sale_price
            item.calc_original_price = i_original_price
            item.calc_fee = i_fee
            item.calc_profit = i_profit

            # externalVendorSku 없는 경우 "-"
            item.rocket_external_vendor_sku = item.rocket_external_vendor_sku or "-"
            item.marketplace_external_vendor_sku = item.marketplace_external_vendor_sku or "-"

    # (C) 템플릿 context
    context = {
        'products': products,
        'grouped_data': grouped_data,
        'total_count': total_count,   # 전체상품 개수
        'search_query': search_query,
        'delivery_filter': delivery_filter,
    }
    return render(request, "sales_management/product_list.html", context)



def parse_coupang_datetime(dt_str):
    if not dt_str:
        return None
    try:
        naive_dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        # naive datetime → aware datetime (예: Asia/Seoul)
        aware_dt = timezone.make_aware(naive_dt, timezone.get_current_timezone())
        return aware_dt
    except ValueError:
        return None
    
def update_coupang_products(request):
    """
    1) 목록 API (fetch_coupang_all_seller_products) → product_list를 받아
       DB에 productId, sellerProductName 등 기본 정보 업데이트
    2) 각 sellerProductId에 대해 상세조회 (get_coupang_seller_product)
       → _save_coupang_product_detail 로 최종 저장
    """
    if request.method == 'POST':
        # (A) 어떤 쿠팡 계정을 쓸지 결정 (예시는 첫 번째만)
        account_info = COUPANG_ACCOUNTS[0]

        # (B) 목록 API
        success, product_list = fetch_coupang_all_seller_products(account_info)
        if not success:
            # 실패 시, product_list는 에러 메시지
            messages.error(request, f"쿠팡 상품 목록 조회 실패: {product_list}")
            return redirect('product_list')

        # product_list = [ { "sellerProductId":..., "productId":..., ... }, ... ]
        #  (C) 목록 기반으로 DB 업데이트 (기본 정보)
        save_product_list_basic_info(product_list)

        # (D) 각 상품에 대해 상세 조회
        count_ok = 0
        for prod in product_list:
            seller_product_id = prod.get('sellerProductId')
            if not seller_product_id:
                continue

            success_detail, detail_data = get_coupang_seller_product(account_info, seller_product_id)
            if success_detail:
                # detail_data = {"sellerProductId":..., "items":[...], ...}
                _save_coupang_product_detail(detail_data)
                count_ok += 1
            else:
                messages.warning(request, f"상세 조회 실패 - ID={seller_product_id}, reason={detail_data}")

        messages.success(request, f"총 {count_ok}개 상품 상세정보를 업데이트했습니다.")
        return redirect('product_list')
    else:
        # GET이면 그냥 redirect
        return redirect('product_list')

def save_product_list_basic_info(product_list):
    """
    product_list: [{"sellerProductId":..., "productId":..., "sellerProductName":..., ...}, ...]

    DB CoupangProduct에 sellerProductId로 update or create:
    - productId: 목록에서 온 값이 있으면 반영
    - sellerProductName 등도 목록 데이터로 반영
    """
    from .models import CoupangProduct

    for p in product_list:
        seller_id = p.get('sellerProductId')
        if not seller_id:
            continue

        new_pid = p.get('productId')  # 목록에 있는 productId
        # 기존 레코드 있는지 체크
        existing = CoupangProduct.objects.filter(sellerProductId=seller_id).first()
        old_pid = existing.productId if existing else None

        final_pid = new_pid if new_pid else old_pid  # 새 pid가 없으면 기존 유지

        defaults_data = {
            'sellerProductName': p.get('sellerProductName'),
            'displayCategoryCode': p.get('displayCategoryCode'),
            'vendorId': p.get('vendorId'),
            'brand': p.get('brand'),
            'statusName': p.get('statusName'),
            'categoryId': p.get('categoryId'),
            # etc. - 목록에서 필요한 다른 필드도 있으면 넣어주세요
            'productId': final_pid,
        }

        CoupangProduct.objects.update_or_create(
            sellerProductId=seller_id,
            defaults=defaults_data
        )

def _save_coupang_product_detail(data):
    """
    (기존 코드) -> 상품 레벨: sellerProductId로 update_or_create
      - productId = 새 값이 있으면 덮어쓰기, 없으면 기존 값 유지
    (옵션 레벨): rocket_vendor_item_id/mk_vendor_item_id 로 update_or_create
    (이미지): create
    """
    from .models import CoupangProduct, CoupangItem, CoupangItemImage
    from django.db.utils import IntegrityError

    seller_product_id = data.get('sellerProductId')
    new_pid = data.get('productId')  # 상세에서 없을 수 있음

    existing = CoupangProduct.objects.filter(sellerProductId=seller_product_id).first()
    old_pid = existing.productId if existing else None
    final_pid = new_pid if new_pid else old_pid

    defaults_product = {
        'code': data.get('code', ''),
        'message': data.get('message', ''),
        'sellerProductName': data.get('sellerProductName'),
        'displayCategoryCode': data.get('displayCategoryCode'),
        'vendorId': data.get('vendorId'),
        'brand': data.get('brand'),
        'productGroup': data.get('productGroup'),
        'statusName': data.get('statusName'),
        'vendorUserId': data.get('vendorUserId'),
        'requested': data.get('requested', False),
        'categoryId': data.get('categoryId'),
        'productId': final_pid,  # 유지
    }

    product_obj, created_p = CoupangProduct.objects.update_or_create(
        sellerProductId=seller_product_id,
        defaults=defaults_product
    )
    # logger.debug(
    #     "[_save_coupang_product_detail] sellerProductId=%s, productId=%s, created=%s",
    #     seller_product_id,
    #     product_obj.productId,
    #     created_p
    # )

    # (5) items 배열
    items_list = data.get('items', [])
    for item_data in items_list:
        # (A) rocketGrowthItemData
        rocket_data = item_data.get('rocketGrowthItemData', {})
        rocket_sku_info = rocket_data.get('skuInfo', {})
        rocket_price_data = rocket_data.get('priceData', {})

        # (B) marketplaceItemData
        marketplace_data = item_data.get('marketplaceItemData', {})
        marketplace_price_data = marketplace_data.get('priceData', {})

        # rocket_external_vendor_sku
        if rocket_data:
            rocket_external_vendor_sku = rocket_data.get('externalVendorSku')
        else:
            rocket_external_vendor_sku = item_data.get('externalVendorSku')

        # marketplace_external_vendor_sku
        if marketplace_data:
            marketplace_external_vendor_sku = marketplace_data.get('externalVendorSku')
        else:
            marketplace_external_vendor_sku = item_data.get('externalVendorSku')

        # 로켓 필드가 없으면 기본값 0/None
        if not rocket_data and not rocket_price_data:
            rocket_seller_product_item_id = None
            rocket_vendor_item_id = None
            rocket_item_id = None
            rocket_barcode = None
            rocket_model_no = None
            rocket_original_price = 0
            rocket_sale_price = 0
            rocket_supply_price = 0
            rocket_height = 0
            rocket_length = 0
            rocket_width = 0
            rocket_weight = 0
            rocket_quantity_per_box = 1
            rocket_stand_alone = False
            rocket_distribution_period = 0
            rocket_expired_at_managed = False
            rocket_manufactured_at_managed = False
            rocket_net_weight = 0
            rocket_heat_sensitive = None
            rocket_hazardous = None
            rocket_original_barcode = None
            rocket_inbound_name = None
            rocket_original_dimension_input_type = None
        else:
            rocket_seller_product_item_id = rocket_data.get('sellerProductItemId')
            rocket_vendor_item_id = rocket_data.get('vendorItemId')
            rocket_item_id = rocket_data.get('itemId')
            rocket_barcode = rocket_data.get('barcode')
            rocket_model_no = rocket_data.get('modelNo')
            rocket_original_price = rocket_price_data.get('originalPrice', 0)
            rocket_sale_price = rocket_price_data.get('salePrice', 0)
            rocket_supply_price = rocket_price_data.get('supplyPrice', 0)

            rocket_height = rocket_sku_info.get('height', 0)
            rocket_length = rocket_sku_info.get('length', 0)
            rocket_width = rocket_sku_info.get('width', 0)
            rocket_weight = rocket_sku_info.get('weight', 0)
            rocket_quantity_per_box = rocket_sku_info.get('quantityPerBox', 1)
            rocket_stand_alone = rocket_sku_info.get('standAlone', False)
            rocket_distribution_period = rocket_sku_info.get('distributionPeriod', 0)
            rocket_expired_at_managed = rocket_sku_info.get('expiredAtManaged', False)
            rocket_manufactured_at_managed = rocket_sku_info.get('manufacturedAtManaged', False)
            rocket_net_weight = rocket_sku_info.get('netWeight') or 0
            rocket_heat_sensitive = rocket_sku_info.get('heatSensitive')
            rocket_hazardous = rocket_sku_info.get('hazardous')
            rocket_original_barcode = rocket_sku_info.get('originalBarcode')
            rocket_inbound_name = rocket_sku_info.get('inboundName')
            rocket_original_dimension_input_type = rocket_sku_info.get('originalDimensionInputType')

        # 마켓 필드도 동일
        if not marketplace_data and not marketplace_price_data:
            mk_seller_product_item_id = item_data.get('sellerProductItemId')
            mk_vendor_item_id = item_data.get('vendorItemId')
            mk_item_id = item_data.get('itemId')
            mk_barcode = item_data.get('barcode')
            mk_model_no = item_data.get('modelNo')
            mk_best_price_3p = item_data.get('bestPriceGuaranteed3P', False)
            mk_original_price = item_data.get('originalPrice', 0)
            mk_sale_price = item_data.get('salePrice', 0)
            mk_supply_price = item_data.get('supplyPrice', 0)
        else:
            mk_seller_product_item_id = marketplace_data.get('sellerProductItemId')
            mk_vendor_item_id = marketplace_data.get('vendorItemId')
            mk_item_id = marketplace_data.get('itemId')
            mk_barcode = marketplace_data.get('barcode')
            mk_model_no = marketplace_data.get('modelNo')
            mk_best_price_3p = marketplace_data.get('bestPriceGuaranteed3P', False)
            mk_original_price = marketplace_price_data.get('originalPrice', 0)
            mk_sale_price = marketplace_price_data.get('salePrice', 0)
            mk_supply_price = marketplace_price_data.get('supplyPrice', 0)

        # vendor_item_id 식별
        unique_filter = {'parent': product_obj}
        if rocket_vendor_item_id:
            unique_filter['rocket_vendor_item_id'] = rocket_vendor_item_id
        elif mk_vendor_item_id:
            unique_filter['marketplace_vendor_item_id'] = mk_vendor_item_id
        else:
            unique_filter = None  # 둘 다 없으면 create

        defaults_data = {
            'itemName': item_data.get('itemName'),
            'unitCount': item_data.get('unitCount', 1),
            'outboundShippingTime': item_data.get('outboundShippingTime', 0),

            'rocket_seller_product_item_id': rocket_seller_product_item_id,
            'rocket_vendor_item_id': rocket_vendor_item_id,
            'rocket_item_id': rocket_item_id,
            'rocket_barcode': rocket_barcode,
            'rocket_model_no': rocket_model_no,
            'rocket_original_price': rocket_original_price,
            'rocket_sale_price': rocket_sale_price,
            'rocket_supply_price': rocket_supply_price,
            'rocket_height': rocket_height,
            'rocket_length': rocket_length,
            'rocket_width': rocket_width,
            'rocket_weight': rocket_weight,
            'rocket_quantity_per_box': rocket_quantity_per_box,
            'rocket_stand_alone': rocket_stand_alone,
            'rocket_distribution_period': rocket_distribution_period,
            'rocket_expired_at_managed': rocket_expired_at_managed,
            'rocket_manufactured_at_managed': rocket_manufactured_at_managed,
            'rocket_net_weight': rocket_net_weight,
            'rocket_heat_sensitive': rocket_heat_sensitive,
            'rocket_hazardous': rocket_hazardous,
            'rocket_original_barcode': rocket_original_barcode,
            'rocket_maximum_buy_count': item_data.get('maximumBuyCount', 0),
            'rocket_inbound_name': rocket_inbound_name,
            'rocket_original_dimension_input_type': rocket_original_dimension_input_type,
            'rocket_external_vendor_sku': rocket_external_vendor_sku,

            'marketplace_seller_product_item_id': mk_seller_product_item_id,
            'marketplace_vendor_item_id': mk_vendor_item_id,
            'marketplace_item_id': mk_item_id,
            'marketplace_barcode': mk_barcode,
            'marketplace_model_no': mk_model_no,
            'marketplace_best_price_guaranteed_3p': mk_best_price_3p,
            'marketplace_original_price': mk_original_price,
            'marketplace_sale_price': mk_sale_price,
            'marketplace_supply_price': mk_supply_price,
            'marketplace_maximum_buy_count': item_data.get('maximumBuyCount', 0),
            'marketplace_external_vendor_sku': marketplace_external_vendor_sku,
        }

        if unique_filter:
            try:
                item_obj, created_i = CoupangItem.objects.update_or_create(
                    defaults=defaults_data,
                    **unique_filter
                )
            except IntegrityError:
                # 혹시 unique 제약 충돌 시 -> create
                item_obj = CoupangItem.objects.create(parent=product_obj, **defaults_data)
        else:
            item_obj = CoupangItem.objects.create(parent=product_obj, **defaults_data)

        # images
        images_array = item_data.get('images', [])
        for img_data in images_array:
            CoupangItemImage.objects.create(
                parent_item=item_obj,
                imageOrder=img_data.get('imageOrder', 0),
                imageType=img_data.get('imageType'),
                cdnPath=img_data.get('cdnPath'),
                vendorPath=img_data.get('vendorPath'),
            )

    return product_obj

def delete_all_coupang_data(request):
    if request.method == 'POST':
        # 예시: CoupangProduct, CoupangItem, CoupangItemImage 전부 삭제
        from .models import CoupangProduct, CoupangItem, CoupangItemImage
        CoupangItemImage.objects.all().delete()
        CoupangItem.objects.all().delete()
        CoupangProduct.objects.all().delete()

        messages.success(request, "모든 쿠팡 데이터를 삭제했습니다.")
        return redirect('product_list')  # or another page
    else:
        return redirect('product_list')













def dashboard_view(request):
    return render(request, 'sales_management/dashboard.html')




def sales_report_view(request):
    logger.info("===== [sales_report_view] START =====")

    # 1) GET 파라미터(start_date, end_date) 받아오기
    start_str = request.GET.get('start_date', '')
    end_str   = request.GET.get('end_date', '')

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date   = datetime.strptime(end_str,   "%Y-%m-%d").date()
        except ValueError:
            # 날짜 파싱 실패 시, 기본 7일
            start_date = date.today() - timedelta(days=14)
            end_date   = date.today() - timedelta(days=1)
    else:
        # 파라미터 없으면 기본 7일
        start_date = date.today() - timedelta(days=14)
        end_date   = date.today() - timedelta(days=1)

    # 2) 전체 날짜 리스트 (오름차순)
    day_count = (end_date - start_date).days + 1
    date_list = [start_date + timedelta(days=i) for i in range(day_count)]

    # (A) 테이블용 dates = 역정렬
    table_dates = [d.strftime('%Y-%m-%d') for d in date_list]
    table_dates.reverse()  # 최근 날짜가 왼쪽

    # (B) 차트용 dates = 오름차순 그대로
    chart_dates = [d.strftime('%Y-%m-%d') for d in date_list]

    # logger.info(f"조회 기간: {start_date} ~ {end_date}, tableDates={table_dates}, chartDates={chart_dates}")

    # 3) DB 필터링
    daily_qs = CoupangDailySales.objects.filter(
        date__range=[start_date, end_date],
    ).filter(
        Q(net_sales_amount__lte=-1) | Q(net_sales_amount__gte=1) |
        Q(net_sold_items__lte=-1)   | Q(net_sold_items__gte=1)
    ).order_by('date')
    # logger.info(f"daily_qs Count={daily_qs.count()}")

    # ---------------------------
    # (I) 테이블용 grouped_data (역정렬)
    # ---------------------------
    grouped_data_dict = {}
    for row in daily_qs:
        product_name = row.product_name or "상품미매핑"
        option_name = row.option_name or row.item_name
        delivery_label = row.delivery_label or "구분없음"
        dstr = row.date.strftime('%Y-%m-%d')

        if product_name not in grouped_data_dict:
            grouped_data_dict[product_name] = {
                "product_name": product_name,
                "delivery_label": delivery_label,
                "product_sales": {},  # { date_str: {qty, revenue} }
                "options": {}
            }

        # 옵션 dict
        if option_name not in grouped_data_dict[product_name]["options"]:
            grouped_data_dict[product_name]["options"][option_name] = {
                "option_name": option_name,
                "delivery_label": delivery_label,
                "option_sales": {}
            }

        # 옵션 레벨
        opt_sales = grouped_data_dict[product_name]["options"][option_name]["option_sales"]
        if dstr not in opt_sales:
            opt_sales[dstr] = {"qty": 0, "revenue": 0}
        opt_sales[dstr]["qty"]     += row.net_sold_items
        opt_sales[dstr]["revenue"] += row.net_sales_amount

        # 상품 레벨
        prod_sales = grouped_data_dict[product_name]["product_sales"]
        if dstr not in prod_sales:
            prod_sales[dstr] = {"qty": 0, "revenue": 0}
        prod_sales[dstr]["qty"]     += row.net_sold_items
        prod_sales[dstr]["revenue"] += row.net_sales_amount

    # 테이블용 date_sums
    date_sums = {td: {"qty":0, "revenue":0} for td in table_dates}
    grand_total_qty = 0
    grand_total_rev = 0

    grouped_data = []
    for prod_key, prod_val in grouped_data_dict.items():
        product_total_qty = 0
        product_total_rev = 0
        # 상품 레벨
        for d_str, val in prod_val["product_sales"].items():
            product_total_qty += val["qty"]
            product_total_rev += val["revenue"]
            if d_str in date_sums:
                date_sums[d_str]["qty"]     += val["qty"]
                date_sums[d_str]["revenue"] += val["revenue"]

        # 옵션
        option_list = []
        for opt_key, opt_val in prod_val["options"].items():
            opt_total_qty = 0
            opt_total_rev = 0
            for d_str, oval in opt_val["option_sales"].items():
                opt_total_qty += oval["qty"]
                opt_total_rev += oval["revenue"]

            option_list.append({
                "option_name": opt_val["option_name"],
                "delivery_label": opt_val["delivery_label"],
                "option_sales": opt_val["option_sales"],
                "option_total": {
                    "qty": opt_total_qty,
                    "revenue": opt_total_rev
                }
            })

        grouped_data.append({
            "product_name": prod_val["product_name"],
            "delivery_label": prod_val["delivery_label"],
            "product_sales": prod_val["product_sales"],
            "product_total": {
                "qty": product_total_qty,
                "revenue": product_total_rev
            },
            "options": option_list
        })
        grand_total_qty += product_total_qty
        grand_total_rev += product_total_rev

    # ---------------------------
    # (II) 차트용 데이터 (오름차순)
    # ---------------------------
    daily_dict = defaultdict(lambda: {
        "total_t_amount": 0,
        "net_s_amount": 0,
        "total_t_items": 0,
        "net_s_items": 0
    })

    for row in daily_qs:
        ddstr = row.date.strftime('%Y-%m-%d')
        daily_dict[ddstr]["total_t_amount"] += int(row.total_transaction_amount)
        daily_dict[ddstr]["net_s_amount"]   += int(row.net_sales_amount)
        daily_dict[ddstr]["total_t_items"]  += row.total_transaction_items
        daily_dict[ddstr]["net_s_items"]    += row.net_sold_items

    chart_data = {
        "labels": chart_dates,  # 오름차순
        "total_t_amount": [],
        "net_s_amount": [],
        "total_t_items": [],
        "net_s_items": []
    }

    # logger.debug(f"chart_dates = {chart_dates}")  
    # logger.debug(f"before fill: chart_data = {chart_data}")


    for d in chart_dates:
        chart_data["total_t_amount"].append(daily_dict[d]["total_t_amount"])
        chart_data["net_s_amount"].append(daily_dict[d]["net_s_amount"])
        chart_data["total_t_items"].append(daily_dict[d]["total_t_items"])
        chart_data["net_s_items"].append(daily_dict[d]["net_s_items"])

    chart_data_json = json.dumps(chart_data)

    # logger.debug(f"after fill: chart_data = {chart_data}")
    # 4) context
    context = {
        # 날짜 파라미터를 그대로 템플릿에 넘겨서 input date의 value에 반영
        "start_date": start_date,
        "end_date": end_date,

        # 테이블(역정렬) 데이터
        "dates": table_dates,
        "grouped_data": grouped_data,
        "date_sums": date_sums,
        "grand_total": {"qty": grand_total_qty, "revenue": grand_total_rev},

        # 차트(오름차순)
        "chart_data_json": chart_data_json,
    }

    # logger.info("===== [sales_report_view] END =====")
    return render(request, "sales_management/sales_report.html", context)

def update_coupang_sales_view(request):
    if request.method == 'POST':
        start_str = request.POST.get('fetch_start_date')
        end_str   = request.POST.get('fetch_end_date')

        if start_str and end_str:
            # call_command('fetch_coupang_sales', --start=..., --end=...)
            call_command('fetch_coupang_sales', start=start_str, end=end_str)
            messages.success(request, f"쿠팡 매출 ({start_str} ~ {end_str}) 업데이트 완료!")
        else:
            messages.warning(request, "날짜를 선택해주세요!")

        return redirect('sales_report')  # or 다른 URL
    else:
        return redirect('sales_report')
    
def sales_excel_file(file_path):
    """
    업로드된 엑셀 파일을 읽어 DB에 저장하는 함수.
    파일명에서 날짜를 추출하고, 각 행을 순회하며 CoupangDailySales 모델에 저장합니다.
    """
    try:
        df = pd.read_excel(file_path, dtype={"옵션ID": str})
        logger.info(f"[엑셀 파싱] 컬럼: {df.columns.tolist()}")
    except Exception as e:
        logger.warning(f"엑셀 파일 읽기 실패: {e}")
        return "엑셀 파일 읽기 실패"

    date_from_filename = None
    # 파일명에서 날짜 정보 추출 (예: Statistics-20250212~20250212_(0).xlsx)
    match = re.search(r"Statistics-.*?(\d{8})~(\d{8})", os.path.basename(file_path))
    if match:
        start_str, end_str = match.group(1), match.group(2)
        # 두 날짜 문자열이 동일한지 검사
        if start_str != end_str:
            logger.info("8자리 날짜가 동일하지 않습니다. 파일 건너뜁니다.")
            return "날짜 범위 불일치"
        try:
            date_from_filename = datetime.strptime(start_str, "%Y%m%d").date()
        except Exception as e:
            logger.error("날짜 파싱 실패: " + str(e))
            return "날짜 파싱 실패"
    else:
        logger.error("날짜 추출 실패. 파일명을 확인해주세요.")
        return "날짜 추출 실패"
    if date_from_filename is None:
        logger.error("날짜 추출 실패. 파일명을 확인해주세요.")
        return "날짜 추출 실패"

    # 엑셀 각 행 순회 및 DB 저장
    for idx, row in df.iterrows():
        if str(row.get("노출상품ID", "")).strip() == "합 계":
            logger.info(f"[{idx}] Summary row detected, skipping.")
            continue

        if pd.isna(row["노출상품ID"]) or pd.isna(row["순 판매 금액(전체 거래 금액 - 취소 금액)"]):
            logger.info(f"[{idx}] 필수 데이터 누락 → 스킵")
            continue

        item_winner_ratio_raw = row.get("아이템위너 비율(%)", "0")
        if pd.isna(item_winner_ratio_raw):
            item_winner_ratio_raw = "0"
        raw_ratio = str(item_winner_ratio_raw)
        ratio_str = raw_ratio.replace('%', '').strip() or '0'
        try:
            item_winner_val = decimal.Decimal(ratio_str)
        except decimal.InvalidOperation:
            logger.info(f"[{idx}] '{raw_ratio}' 숫자 변환 실패, skipping")
            continue

        raw_item_name = str(row["옵션명"])
        if "," in raw_item_name:
            parts = raw_item_name.split(",", 1)
            product_str = parts[0].strip()
            option_str = parts[1].strip()
        else:
            product_str = raw_item_name
            option_str = None

        try:
            net_sales_val = int(row["순 판매 금액(전체 거래 금액 - 취소 금액)"])
        except:
            net_sales_val = 0
        try:
            total_trans_val = int(row["전체 거래 금액"])
        except:
            total_trans_val = 0
        try:
            total_cancel_val = int(row["총 취소 금액"])
        except:
            total_cancel_val = 0
        try:
            net_sold_items_val = int(row["순 판매 상품 수(전체 거래 상품 수 - 취소 상품 수)"])
        except:
            net_sold_items_val = 0
        try:
            total_trans_items_val = int(row["전체 거래 상품 수"])
        except:
            total_trans_items_val = 0
        try:
            total_cancel_items_val = int(row["총 취소 상품 수"])
        except:
            total_cancel_items_val = 0
        try:
            immediate_cancel_items_val = int(row["즉시 취소 상품 수"])
        except:
            immediate_cancel_items_val = 0

        sku_str = str(row["옵션ID"])

        record = CoupangDailySales(
            displayed_product_id=row["노출상품ID"],
            sku_id=sku_str,
            item_name=raw_item_name,
            product_name=product_str,
            option_name=option_str,
            delivery_label=row["상품타입"],
            category_name=row["카테고리"],
            item_winner_ratio=item_winner_val,
            net_sales_amount=net_sales_val,
            net_sold_items=net_sold_items_val,
            total_transaction_amount=total_trans_val,
            total_transaction_items=total_trans_items_val,
            total_cancellation_amount=total_cancel_val,
            total_cancelled_items=total_cancel_items_val,
            immediate_cancellation_items=immediate_cancel_items_val,
            date=date_from_filename,
        )
        try:
            record.save()
        except Exception as e:
            logger.exception(f"DB 저장 실패, 행({idx}): {e}")

    os.remove(file_path)
    logger.info(f"파일 처리 완료 후 삭제: {os.path.basename(file_path)}")
    # sales_excel_file 함수에서는 redirect를 리턴하지 않고 결과 메시지를 반환
    return "파일 처리 완료"


def upload_excel_view(request):
    """
    엑셀 파일 업로드 폼을 렌더링하거나, 업로드된 파일들을 처리하는 뷰.
    POST 요청 시 파일들을 임시 디렉토리에 저장한 후, sales_excel_file 함수를 각 파일에 대해 호출하고
    사용자가 있던 이전 URL로 리다이렉트합니다.
    """
    if request.method == 'POST':
        excel_files = request.FILES.getlist('excel_file')
        if not excel_files:
            return HttpResponse("업로드된 파일이 없습니다.")
        tmp_dir = os.path.join(settings.BASE_DIR, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        results = []
        for excel_file in excel_files:
            file_path = os.path.join(tmp_dir, excel_file.name)
            with open(file_path, 'wb') as f:
                for chunk in excel_file.chunks():
                    f.write(chunk)
            result = sales_excel_file(file_path)
            results.append(f"{excel_file.name}: {result}")
        # 업로드 후 이전 페이지로 리다이렉트합니다.
        # 필요하면 results를 세션에 저장하거나 쿼리 파라미터로 전달할 수 있습니다.
        return redirect(request.META.get('HTTP_REFERER', 'sales_report'))
    else:
        return render(request, 'sales_report.html')


#광고 리포트 시작
def update_ads_report(request):
    """
    1) POST로 넘어온 날짜 범위(fetch_start_date, fetch_end_date)를 받아서
    2) `fetch_coupang_ads` 커맨드를 실행 → 엑셀 다운로드 & DB 업데이트
    3) 완료 후 메시지를 띄우고 '/sales/ad-report/' 페이지로 (날짜 쿼리스트링 포함) 리다이렉트
    """
    if request.method == 'POST':
        from datetime import datetime
        from django.shortcuts import redirect
        from django.core.management import call_command
        from django.contrib import messages
        
        # (A) POST 파라미터로 start/end 날짜 받기
        start_str = request.POST.get('fetch_start_date', '')
        end_str   = request.POST.get('fetch_end_date', '')

        # (B) 날짜가 비어있거나 형식이 잘못되었다면, 기본값으로 처리(선택 사항)
        if not start_str:
            start_str = datetime.now().strftime('%Y-%m-%d')
        if not end_str:
            end_str = start_str

        # (C) 관리 명령어 실행
        try:
            call_command('fetch_coupang_ads',
                         f'--start={start_str}',
                         f'--end={end_str}')
            messages.success(request,
                f"쿠팡 광고 데이터 업데이트가 완료되었습니다. ({start_str} ~ {end_str})")
        except Exception as e:
            messages.error(request,
                f"업데이트 중 오류가 발생했습니다: {e}")

        # (D) 리다이렉트할 때 GET 파라미터로 start_date, end_date 포함
        redirect_url = f'/sales/ad-report/?start_date={start_str}&end_date={end_str}'
        return redirect(redirect_url)

    else:
        # GET 요청 등은 직접 접근하지 않고, /sales/ad-report/로 돌려보냄
        from django.contrib import messages
        messages.info(request, "잘못된 접근입니다.")
        return redirect('/sales/ad-report/')




def convert_keys(obj):
    """
    딕셔너리의 키가 datetime 등의 직렬화 불가능한 타입이면
    string으로 변환해주는 유틸 함수(재귀).
    프로젝트 내에서 이미 구현되어 있을 수 있으므로,
    중복 시 제거하거나 필요에 맞게 수정해도 됨.
    """
    import collections

    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            new_k = str(k)  # 키를 문자열로
            new_dict[new_k] = convert_keys(v)
        return new_dict
    elif isinstance(obj, list):
        return [convert_keys(elem) for elem in obj]
    else:
        return obj


def ad_report_view(request):
    """
    광고 판매 현황 리포트:
      - 설정된 전체 기간의 CoupangDailySales와 CoupangAdsReport 데이터를 한 번 조회하여,
        (A) 일자별 요약(소계) 테이블,
        (B) 각 일자별 소계의 하위행(배송라벨별 detail),
        (C) 전체 기간 합계(일자별 리포트 기반),
        (D) 상품/옵션별 상세(모달용) 데이터,
      - 그리고 최근 14일 기준 KPI 카드(ROAS 600% 이상, ROAS 200% 이하, 전환율 평균 이하)를 함께 생성한다.
      - 배송라벨은 SKU를 기반으로 '로켓그로스' 또는 '판매자배송'으로 결정한다.
    """
    from datetime import date, datetime, timedelta
    from collections import defaultdict, OrderedDict
    import json
    from django.db.models import Sum
    from django.shortcuts import render
    from sales_management.models import (
        CoupangDailySales, 
        CoupangAdsReport, 
        CoupangItem, 
        PurchaseCost
    )

    # --------------------------
    # 1) 날짜 범위 파싱
    start_str = request.GET.get('start_date', '')
    end_str   = request.GET.get('end_date', '')
    if not start_str or not end_str:
        start_d = date.today() - timedelta(days=14)
        end_d = date.today() - timedelta(days=1)
    else:
        try:
            start_d = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_d   = datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            start_d = date.today() - timedelta(days=14)
            end_d   = date.today() - timedelta(days=1)

    # --------------------------
    # 2) 배송라벨 결정 로직
    rocket_sku = set(
        map(str, CoupangItem.objects.exclude(rocket_vendor_item_id__isnull=True)
            .values_list('rocket_vendor_item_id', flat=True))
    )
    market_sku = set(
        map(str, CoupangItem.objects.exclude(marketplace_vendor_item_id__isnull=True)
            .values_list('marketplace_vendor_item_id', flat=True))
    )
    def get_label_from_sku(sku_str):
        if sku_str in rocket_sku:
            return "로켓그로스"
        elif sku_str in market_sku:
            return "판매자배송"
        else:
            return "판매자배송"  # 기본값

    # --------------------------
    # 3) 일자별 집계를 위한 데이터 조회
    #    (A) 판매 측 (DailySales)
    daily_grouped = (
        CoupangDailySales.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'sku_id')
        .annotate(
            sold_items=Sum('net_sold_items'),
            total_tx=Sum('total_transaction_amount'),
            net_sales=Sum('net_sales_amount')
        )
    )
    #    (B) 광고 측 (AdsReport)
    ads_grouped = (
        CoupangAdsReport.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'executed_option_id')
        .annotate(
            ad_sold=Sum('sold_quantity'),
            orders_sum=Sum('orders'),
            clicks_sum=Sum('clicks'),
            ad_spend=Sum('ad_spend'),
            ad_rev=Sum('sales_amount')
        )
    )

    # --------------------------
    # 4) daily_map / ads_map (keyed by (date, label))
    #
    #    - daily_map[d, label] => 판매집계(판매수량, 매출, 순매출)
    #    - ads_map[d, label]   => 광고집계(광고판매수량, 광고비, 광고전환매출, etc.)
    from collections import defaultdict

    daily_map = defaultdict(lambda: {"sold_items": 0, "total_tx": 0, "net_sales": 0})
    for row in daily_grouped:
        d = row["date"]
        sku_str = str(row["sku_id"])
        label = get_label_from_sku(sku_str)
        key = (d, label)

        daily_map[key]["sold_items"] += (row["sold_items"] or 0)
        daily_map[key]["total_tx"]   += (row["total_tx"] or 0)
        daily_map[key]["net_sales"]  += (row["net_sales"] or 0)

    ads_map = defaultdict(lambda: {"ad_sold": 0, "orders": 0, "clicks": 0, "ad_spend": 0, "ad_rev": 0})
    for ad in ads_grouped:
        d = ad["date"]
        sku_str = str(ad["executed_option_id"])
        label = get_label_from_sku(sku_str)
        key = (d, label)

        ads_map[key]["ad_sold"]  += (ad["ad_sold"] or 0)
        ads_map[key]["orders"]   += (ad["orders_sum"] or 0)
        ads_map[key]["clicks"]   += (ad["clicks_sum"] or 0)
        ads_map[key]["ad_spend"] += (ad["ad_spend"] or 0)
        ads_map[key]["ad_rev"]   += (ad["ad_rev"] or 0)

    # --------------------------
    # 5) 결합: date_label_map[date][label] = {판매/광고종합}
    #    - 광고판매비율(ad_sales_rate) = 광고판매수량 / 판매수량 * 100
    #    - ROAS = 광고전환매출 / 광고집행비 * 100
    #    - profit = (광고전환매출) - (광고집행비)  (필요하다면 다른 계산으로)
    #    - conversion_rate = (orders / clicks * 100)
    date_label_map = defaultdict(dict)
    all_keys = set(daily_map.keys()) | set(ads_map.keys())
     # --- 섹션 5) 라벨별 합산 (orders, clicks 포함) ---
    for (d, lbl) in all_keys:
        sold = daily_map[(d, lbl)]
        ad = ads_map[(d, lbl)]
        orders_val = ad["orders"] or 0
        clicks_val = ad["clicks"] or 0
        conversion_rate = (orders_val / clicks_val * 100) if clicks_val > 0 else 0

        if sold["sold_items"] > 0:
            ad_sales_rate = (ad["ad_sold"] / sold["sold_items"]) * 100
        else:
            ad_sales_rate = 0

        roas = (ad["ad_rev"] / ad["ad_spend"] * 100) if ad["ad_spend"] else 0
        profit = ad["ad_rev"] - ad["ad_spend"]

        date_label_map[d][lbl] = {
            "kind": lbl,
            "qty": sold["sold_items"],
            "ad_qty": ad["ad_sold"],
            "orders": orders_val,
            "clicks": clicks_val,
            "conversion_rate": conversion_rate,
            "revenue": sold["total_tx"],
            "net_sales_amount": sold["net_sales"],
            "ad_revenue": ad["ad_rev"],
            "ad_spend": ad["ad_spend"],
            "profit": profit,
            "roas": roas,
            "ad_sales_rate": ad_sales_rate
        }

    # --- 섹션 6) 일자별 리포트 생성 ---
    sorted_dates = sorted(date_label_map.keys())
    daily_reports = []
    for d in sorted_dates:
        label_map = date_label_map[d]
        if not label_map:
            continue

        sum_qty    = sum(item["qty"] for item in label_map.values())
        sum_ad_qty = sum(item["ad_qty"] for item in label_map.values())
        sum_rev    = sum(item["revenue"] for item in label_map.values())
        sum_net    = sum(item["net_sales_amount"] for item in label_map.values())
        sum_ad_rev = sum(item["ad_revenue"] for item in label_map.values())
        sum_ad_spend = sum(item["ad_spend"] for item in label_map.values())
        sum_profit = sum(item["profit"] for item in label_map.values())

        total_orders = sum(item["orders"] for item in label_map.values())
        total_clicks = sum(item.get("clicks", 0) for item in label_map.values())
        day_conv = (total_orders / total_clicks * 100) if total_clicks else 0

        day_roas = (sum_ad_rev / sum_ad_spend * 100) if sum_ad_spend else 0

        day_ad_sales_rate = (sum_ad_qty / sum_qty * 100) if sum_qty else 0

        details = []
        for lbl, data in label_map.items():
            details.append({
                "kind": lbl,
                "qty": data["qty"],
                "ad_qty": data["ad_qty"],
                "conversion_rate": data["conversion_rate"],
                "revenue": data["revenue"],
                "net_sales_amount": data["net_sales_amount"],
                "ad_revenue": data["ad_revenue"],
                "ad_spend": data["ad_spend"],
                "profit": data["profit"],
                "roas": data["roas"],
                "ad_sales_rate": data["ad_sales_rate"]
            })
        order_map = {"로켓그로스": 0, "판매자배송": 1}
        details.sort(key=lambda d: order_map.get(d["kind"], 999))

        daily_reports.append({
            "date_str": d.strftime("%Y-%m-%d"),
            "qty": sum_qty,
            "ad_qty": sum_ad_qty,
            "conversion_rate": day_conv,
            "revenue": sum_rev,
            "net_sales_amount": sum_net,
            "ad_revenue": sum_ad_rev,
            "ad_spend": sum_ad_spend,
            "profit": sum_profit,
            "roas": day_roas,
            "ad_sales_rate": day_ad_sales_rate,
            "orders": total_orders,
            "clicks": total_clicks,
            "details": details
        })

    # --- 섹션 7) 전체 기간 합계 ---
    sum_dict = {
        "qty": 0,
        "ad_qty": 0,
        "revenue": 0,
        "net_sales": 0,
        "ad_revenue": 0,
        "ad_spend": 0,
        "profit": 0,
        "orders": 0,
        "clicks": 0
    }
    for day in daily_reports:
        sum_dict["qty"] += day["qty"]
        sum_dict["ad_qty"] += day["ad_qty"]
        sum_dict["revenue"] += day["revenue"]
        sum_dict["net_sales"] += day["net_sales_amount"]
        sum_dict["ad_revenue"] += day["ad_revenue"]
        sum_dict["ad_spend"] += day["ad_spend"]
        sum_dict["profit"] += day["profit"]
        sum_dict["orders"] += day.get("orders", 0)
        sum_dict["clicks"] += day.get("clicks", 0)

    avg_conv = (sum_dict["orders"] / sum_dict["clicks"] * 100) if sum_dict["clicks"] else 0
    avg_roas = (sum_dict["ad_revenue"] / sum_dict["ad_spend"] * 100) if sum_dict["ad_spend"] else 0
    avg_ad_sales_rate = (sum_dict["ad_qty"] / sum_dict["qty"] * 100) if sum_dict["qty"] else 0

    period_summary = {
        "total_qty": sum_dict["qty"],
        "total_ad_qty": sum_dict["ad_qty"],
        "conversion_rate": avg_conv,
        "total_revenue": sum_dict["revenue"],
        "net_sales_amount": sum_dict["net_sales"],
        "ad_revenue": sum_dict["ad_revenue"],
        "ad_spend": sum_dict["ad_spend"],
        "profit": sum_dict["profit"],
        "roas": avg_roas,
        "ad_sales_rate": avg_ad_sales_rate
    }

    # --------------------------
    # 8) 전체 기간 상세 집계 (일자별 리포트에 있는 detail을 라벨별로 합산)
    #    - period_details[kind] = 로켓그로스, 판매자배송별 합계
    period_details = {}
    for day in daily_reports:
        for detail in day["details"]:
            kind = detail["kind"]
            if kind not in period_details:
                period_details[kind] = detail.copy()
                period_details[kind]["_count"] = 1
            else:
                # 누적
                for field in ["qty", "ad_qty", "net_sales_amount", "revenue", "ad_revenue", "ad_spend", "profit"]:
                    period_details[kind][field] += detail[field]
                period_details[kind]["conversion_rate"] += detail["conversion_rate"]
                period_details[kind]["roas"] += detail["roas"]
                period_details[kind]["ad_sales_rate"] += detail["ad_sales_rate"]
                period_details[kind]["_count"] += 1

    # 평균 필드들 나눠주기
    for kind, agg in period_details.items():
        c = agg["_count"]
        if c > 0:
            agg["conversion_rate"] /= c
            agg["roas"] /= c
            agg["ad_sales_rate"] /= c
        del agg["_count"]

    # --------------------------
    # 9) (모달용) 일자별 상품/옵션별 데이터
    #
    #    광고판매수량 = ad_sold
    #    광고판매비율(ad_sales_rate)은 “ad_sold / sold_qty * 100” 형태로 만들 수 있음
    #
    from collections import defaultdict, OrderedDict

    day_p_o_map = defaultdict(lambda: {
        "sold_qty": 0,
        "net_sales": 0,
        "purchase_cost": 0,
        "ad_sold": 0,
        "ad_spend": 0,
        "ad_revenue": 0,
    })

    # (A) 판매데이터 (날짜 + SKU 단위 매핑)
    sales_qs_modal = (
        CoupangDailySales.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'sku_id',
                'displayed_product_id', 'product_name', 'option_name', 'delivery_label')
        .annotate(
            sold_qty=Sum('net_sold_items'),
            net_sales=Sum('net_sales_amount')
        )
    )

    # (sku, 날짜) -> (disp_id, option_name, label, product_name)
    sku_date_info = {}

    for row in sales_qs_modal:
        d_str = row["date"].strftime("%Y-%m-%d")
        sku = str(row["sku_id"])
        disp_id = row["displayed_product_id"]
        o_name = row["option_name"] or "(옵션없음)"
        label = row["delivery_label"] or ""
        p_name = row["product_name"] or "(상품명없음)"

        sold_qty = row["sold_qty"] or 0
        net_sales = row["net_sales"] or 0

        sku_date_info[(sku, d_str)] = (disp_id, o_name, label, p_name)

        # 매입가
        try:
            cost_obj = PurchaseCost.objects.get(sku_id=sku)
            purchase_c = cost_obj.purchasing_price * sold_qty
        except PurchaseCost.DoesNotExist:
            purchase_c = 0

        # day_p_o_map[(날짜, disp_id, 옵션명, 라벨)]에 누적
        key = (d_str, disp_id, o_name, label)
        day_p_o_map[key]["sold_qty"] += sold_qty
        day_p_o_map[key]["net_sales"] += net_sales
        day_p_o_map[key]["purchase_cost"] += purchase_c

    # (B) 광고데이터
    ads_qs_modal = (
        CoupangAdsReport.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'executed_option_id')
        .annotate(
            ad_sold=Sum('sold_quantity'),
            ad_spend=Sum('ad_spend'),
            sales_amount=Sum('sales_amount')
        )
    )

    for ad_row in ads_qs_modal:
        d_str = ad_row["date"].strftime("%Y-%m-%d")
        sku = str(ad_row["executed_option_id"])

        ad_sold = ad_row["ad_sold"] or 0
        ad_spend = ad_row["ad_spend"] or 0
        ad_rev = ad_row["sales_amount"] or 0

        if (sku, d_str) in sku_date_info:
            disp_id, o_name, label, p_name = sku_date_info[(sku, d_str)]
        else:
            # 광고만 있고 판매가 전혀 없는 경우
            disp_id, o_name, label, p_name = ("unknown", "(옵션X)", "판매자배송", "(광고만 있음)")

        key = (d_str, disp_id, o_name, label)
        day_p_o_map[key]["ad_sold"] += ad_sold
        day_p_o_map[key]["ad_spend"] += ad_spend
        day_p_o_map[key]["ad_revenue"] += ad_rev

    # (C) day_products_map: {날짜: { (disp_id, label): {...} }}
    day_products_map = defaultdict(lambda: OrderedDict())
    for (d_str, disp_id, o_name, label), vals in day_p_o_map.items():
        sold_qty  = vals["sold_qty"]
        net_sales = vals["net_sales"]
        purchase_c= vals["purchase_cost"]
        ad_sold   = vals["ad_sold"]
        ad_spend  = vals["ad_spend"]
        ad_rev    = vals["ad_revenue"]

        profit_val = net_sales - ad_spend - purchase_c
        roas_val   = (ad_rev / ad_spend * 100) if ad_spend else 0
        # 광고판매비율(= ad_sold / sold_qty) 등은 실제 표에서 계산 가능
        # 필요하다면 여기서도 ad_sales_rate_val = (ad_sold / sold_qty)*100 if sold_qty else 0

        prod_key = (disp_id, label)
        if prod_key not in day_products_map[d_str]:
            # 모달에서 보여줄 상위(product) 행
            day_products_map[d_str][prod_key] = {
                "product_name": None,  # 아래에서 o_name등 첫 옵션 때 할당해도 OK
                "qty": 0,
                "ad_qty": 0,
                "net_sales_amount": 0,
                "ad_spend": 0,
                "ad_revenue": 0,
                "profit": 0,
                "roas": 0,
                "options": []
            }

        # 상위행 누적
        pinfo = day_products_map[d_str][prod_key]
        pinfo["product_name"] = p_name  # 매번 넣어도 동일
        pinfo["qty"] += sold_qty
        pinfo["ad_qty"] += ad_sold
        pinfo["net_sales_amount"] += net_sales
        pinfo["ad_spend"] += ad_spend
        pinfo["ad_revenue"] += ad_rev
        pinfo["profit"] += profit_val
        # ROAS는 최종적으로 다시 계산(합계 기준)
        # 일단 현재 항목만 반영
        # → 여러 옵션이 있다면 아래에서 최종 합산 후 계산이 깔끔
        # 임시로: pinfo["roas"] += roas_val  (옵션별 평균이 필요없다면 마지막에 재계산)

        # 옵션 상세
        opt_dict = {
            "option_name": o_name,
            "qty": sold_qty,
            "ad_qty": ad_sold,
            "net_sales_amount": net_sales,
            "ad_spend": ad_spend,
            "ad_revenue": ad_rev,
            "profit": profit_val,
            "roas": roas_val,
            "label": label
        }
        pinfo["options"].append(opt_dict)

    # (D) 옵션 합산 & ROAS 재계산
    for d_key in list(day_products_map.keys()):
        for prod_key in list(day_products_map[d_key].keys()):
            pinfo = day_products_map[d_key][prod_key]
            # 옵션 중 모두 0이면 제거
            pinfo["options"] = [
                opt for opt in pinfo["options"]
                if not (
                    opt["qty"] == 0 and
                    opt["ad_qty"] == 0 and
                    opt["net_sales_amount"] == 0 and
                    opt["ad_spend"] == 0 and
                    opt["profit"] == 0
                )
            ]
            if not pinfo["options"]:
                del day_products_map[d_key][prod_key]
            else:
                # 최종 합계값으로 ROAS, 광고판매비율 등 재계산
                # (ad_sales_rate = ad_qty / qty * 100)
                total_qty    = pinfo["qty"]
                total_ad_qty = pinfo["ad_qty"]
                total_rev    = pinfo["ad_revenue"]
                total_spend  = pinfo["ad_spend"]

                roas_final = (total_rev / total_spend * 100) if total_spend else 0
                ad_sales_rate_final = (total_ad_qty / total_qty * 100) if total_qty else 0
                pinfo["roas"] = roas_final
                pinfo["ad_sales_rate"] = ad_sales_rate_final

    # --------------------------
    # 10) 전체 기간 상품/옵션 집계 (period_products_map)
    #     - 날짜 구분 없이 SKU 단위로 합산
    period_p_o_map = defaultdict(lambda: {
        "sold_qty": 0,
        "net_sales": 0,
        "purchase_cost": 0,
        "ad_sold": 0,
        "ad_spend": 0,
        "ad_revenue": 0
    })
    period_sku_mapping = {}
    period_product_name_mapping = {}

    # (A) sales_data_modal 재활용
    sales_data_modal = list(sales_qs_modal)
    for row in sales_data_modal:
        disp_id = row["displayed_product_id"]
        p_name = row["product_name"] or "(상품명없음)"
        o_name = row["option_name"] or "(옵션없음)"
        label = row["delivery_label"] or ""
        sold_qty = row["sold_qty"] or 0
        net_sales = row["net_sales"] or 0

        sku = str(row["sku_id"])
        period_sku_mapping[sku] = (disp_id, o_name, label)
        period_product_name_mapping[disp_id] = p_name

        try:
            cost_obj = PurchaseCost.objects.get(sku_id=sku)
            purchase_c = cost_obj.purchasing_price * sold_qty
        except PurchaseCost.DoesNotExist:
            purchase_c = 0

        key = (disp_id, o_name, label)
        period_p_o_map[key]["sold_qty"] += sold_qty
        period_p_o_map[key]["net_sales"] += net_sales
        period_p_o_map[key]["purchase_cost"] += purchase_c

    # (B) 광고데이터
    ads_data_modal = list(ads_qs_modal)
    for ad_row in ads_data_modal:
        sku = str(ad_row["executed_option_id"])
        ad_sold = ad_row["ad_sold"] or 0
        ad_spend = ad_row["ad_spend"] or 0
        ad_rev = ad_row["sales_amount"] or 0

        if sku not in period_sku_mapping:
            # 광고만 있고 판매가 전혀 없으면 skip?
            # or 임시로 넣을 수도 있음
            continue

        disp_id, o_name, label = period_sku_mapping[sku]
        key = (disp_id, o_name, label)
        period_p_o_map[key]["ad_sold"] += ad_sold
        period_p_o_map[key]["ad_spend"] += ad_spend
        period_p_o_map[key]["ad_revenue"] += ad_rev

    # (C) period_products_map
    period_products_map = OrderedDict()
    for (disp_id, o_name, label), vals in period_p_o_map.items():
        sold_qty   = vals["sold_qty"]
        net_sales  = vals["net_sales"]
        purchase_c = vals["purchase_cost"]
        ad_sold    = vals["ad_sold"]
        ad_spend   = vals["ad_spend"]
        ad_rev     = vals["ad_revenue"]

        commission = net_sales * 0.1188  # 필요하다면 조정
        profit = net_sales - commission - ad_spend - purchase_c
        margin_rate = (profit / net_sales * 100) if net_sales else 0
        roas = (ad_rev / ad_spend * 100) if ad_spend else 0
        # 광고판매비율을 "광고판매수량 / 판매수량" 기준으로 할지,
        # 혹은 "광고전환매출 / 순매출"로 할지 상황에 맞게 결정
        ad_sales_rate = (ad_sold / sold_qty * 100) if sold_qty else 0

        prod_key = f"{disp_id}_{label}"
        if prod_key not in period_products_map:
            period_products_map[prod_key] = {
                "product_name": period_product_name_mapping.get(disp_id, "(상품명없음)"),
                "qty": 0,
                "ad_qty": 0,
                "net_sales_amount": 0,
                "ad_spend": 0,
                "purchase_cost": 0,
                "commission": 0,
                "profit": 0,
                "margin_rate": 0,
                "ad_revenue": 0,
                "roas": 0,
                "ad_sales_rate": 0,
                "options": []
            }

        option_dict = {
            "option_name": o_name,
            "qty": sold_qty,
            "ad_qty": ad_sold,
            "net_sales_amount": net_sales,
            "purchase_cost": purchase_c,
            "ad_spend": ad_spend,
            "commission": commission,
            "profit": profit,
            "margin_rate": margin_rate,
            "ad_revenue": ad_rev,
            "roas": roas,
            "ad_sales_rate": ad_sales_rate,
            "label": label
        }
        period_products_map[prod_key]["options"].append(option_dict)

    # (D) 옵션 합산
    for prod_key in list(period_products_map.keys()):
        pinfo = period_products_map[prod_key]
        pinfo["options"] = [
            opt for opt in pinfo["options"]
            if not (
                opt["qty"] == 0 and 
                opt["ad_qty"] == 0 and 
                opt["net_sales_amount"] == 0 and
                opt["ad_spend"] == 0 and 
                opt["purchase_cost"] == 0 and 
                opt["profit"] == 0
            )
        ]
        if not pinfo["options"]:
            del period_products_map[prod_key]
        else:
            sum_qty   = sum(opt["qty"] for opt in pinfo["options"])
            sum_adqty = sum(opt["ad_qty"] for opt in pinfo["options"])
            sum_net   = sum(opt["net_sales_amount"] for opt in pinfo["options"])
            sum_pc    = sum(opt["purchase_cost"] for opt in pinfo["options"])
            sum_spend = sum(opt["ad_spend"] for opt in pinfo["options"])
            sum_adrev = sum(opt["ad_revenue"] for opt in pinfo["options"])

            commission = sum_net * 0.1188
            profit_val = sum_net - commission - sum_spend - sum_pc
            margin_rate_val = (profit_val / sum_net * 100) if sum_net else 0
            roas_val = (sum_adrev / sum_spend * 100) if sum_spend else 0
            ad_sales_rate_val = (sum_adqty / sum_qty * 100) if sum_qty else 0

            pinfo["qty"] = sum_qty
            pinfo["ad_qty"] = sum_adqty
            pinfo["net_sales_amount"] = sum_net
            pinfo["ad_spend"] = sum_spend
            pinfo["purchase_cost"] = sum_pc
            pinfo["commission"] = commission
            pinfo["profit"] = profit_val
            pinfo["margin_rate"] = margin_rate_val
            pinfo["ad_revenue"] = sum_adrev
            pinfo["roas"] = roas_val
            pinfo["ad_sales_rate"] = ad_sales_rate_val

    # --------------------------
    # (F) 매입가 0원인 옵션 목록
    zero_purchase_list = []
    zero_costs = PurchaseCost.objects.filter(purchasing_price=0)
    for pc in zero_costs:
        item = CoupangDailySales.objects.filter(sku_id=pc.sku_id).first()
        if item:
            zero_purchase_list.append({
                "product_name": item.product_name or "(상품명없음)",
                "option_name": item.option_name or "(옵션없음)",
                "option_code": getattr(pc, 'option_code', ""),
                "purchasing_price": pc.purchasing_price,
            })

    # --------------------------
    # (G) JSON 직렬화 (모달용)
    def convert_keys(obj):
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                new_obj[str(k)] = convert_keys(v)
            return new_obj
        elif isinstance(obj, list):
            return [convert_keys(item) for item in obj]
        else:
            return obj

    day_products_map_json = json.dumps(convert_keys(day_products_map), ensure_ascii=False, default=str)
    period_products_map_json = json.dumps(convert_keys(period_products_map), ensure_ascii=False, default=str)

    # --------------------------
    # (H) --- KPI 카드 (최근 14일 기준) ---
    kpi_end = date.today()
    kpi_start = kpi_end - timedelta(days=14)
    sales_qs_kpi = (
        CoupangDailySales.objects
        .filter(date__range=[kpi_start, kpi_end])
        .values('sku_id', 'displayed_product_id', 'product_name', 'option_name', 'delivery_label')
        .annotate(
            total_sold=Sum('net_sold_items'),
            total_revenue=Sum('total_transaction_amount'),
            total_net_sales=Sum('net_sales_amount')
        )
    )
    ads_qs_kpi = (
        CoupangAdsReport.objects
        .filter(date__range=[kpi_start, kpi_end])
        .values('executed_option_id')
        .annotate(
            total_ad_sold=Sum('sold_quantity'),
            total_ad_spend=Sum('ad_spend'),
            total_ad_rev=Sum('sales_amount'),
            total_orders=Sum('orders'),
            total_clicks=Sum('clicks'),
            total_impressions=Sum('impressions')  # 가정
        )
    )
    sales_data_kpi = {}
    for row in sales_qs_kpi:
        sku = str(row['sku_id'])
        sales_data_kpi[sku] = row

    ads_data_kpi = {}
    for row in ads_qs_kpi:
        sku = str(row['executed_option_id'])
        ads_data_kpi[sku] = row

    card_items = []
    for sku, s_data in sales_data_kpi.items():
        a_data = ads_data_kpi.get(sku)
        product_name = s_data.get('product_name') or '(상품명없음)'
        option_name = s_data.get('option_name') or '(옵션없음)'
        delivery_label = s_data.get('delivery_label') or ""
        net_sales = s_data.get('total_net_sales') or 0
        revenue = s_data.get('total_revenue') or 0

        if a_data:
            ad_rev = a_data.get('total_ad_rev') or 0
            ad_spend = a_data.get('total_ad_spend') or 0
            orders = a_data.get('total_orders') or 0
            clicks = a_data.get('total_clicks') or 0
            roas_val = (ad_rev / ad_spend * 100) if ad_spend else 0
            conv_rate = (orders / clicks * 100) if clicks else 0
            impressions = a_data.get('total_impressions') or 0
            ctr_val = (clicks / impressions * 100) if impressions else 0
        else:
            ad_rev = 0
            ad_spend = 0
            orders = 0
            clicks = 0  # 추가
            roas_val = 0
            conv_rate = 0
            impressions = 0
            ctr_val = 0

        card_items.append({
            "sku": sku,
            "product_name": product_name,
            "option_name": option_name,
            "delivery_label": delivery_label,
            "roas": roas_val,
            "conversion_rate": conv_rate,
            "net_sales": net_sales,
            "ad_revenue": ad_rev,
            "ad_spend": ad_spend,
            "total_clicks": clicks,
            "total_impressions": impressions,
            "ctr": ctr_val,
        })

    roas_high = [item for item in card_items if item["roas"] >= 600 and item["ad_spend"] >= 10000]
    roas_low  = [item for item in card_items if item["roas"] <= 200 and item["ad_spend"] >= 10000]
    overall_conv_avg = (sum(i["conversion_rate"] for i in card_items) / len(card_items)) if card_items else 0
    conv_low = [i for i in card_items if i["conversion_rate"] < overall_conv_avg and i["conversion_rate"] > 0]

    roas_high.sort(key=lambda x: x["roas"], reverse=True)
    roas_low.sort(key=lambda x: x["roas"])
    conv_low.sort(key=lambda x: x["conversion_rate"])

    # --------------------------
    # 최종 컨텍스트 구성
    context = {
        # 기간
        "start_date": start_d,
        "end_date": end_d,

        # (A) 일자별 요약 테이블
        "daily_reports": daily_reports,         
        # (B) 전체 기간 합계
        "period_summary": period_summary,
        # (C) 전체 기간 상세 (라벨별 합계)
        "period_details": period_details,

        # (D) 모달용 JSON
        "day_products_map_json": day_products_map_json,
        "period_products_map_json": period_products_map_json,

        # 기타
        "zero_purchase_list": zero_purchase_list,
        "roas_high": roas_high,
        "roas_low": roas_low,
        "conv_low": conv_low,
    }

    return render(request, "sales_management/ad_report.html", context)



def ads_excel_file(file_path):
    """
    업로드된 광고 리포트 엑셀 파일을 읽어 DB에 저장하는 함수.
    파일 내 각 행을 순회하며 CoupangAdsReport 모델에 저장합니다.
    """
    logger.info(f"Processing ads report Excel file: {os.path.basename(file_path)}")
    try:
        df = pd.read_excel(file_path)
        logger.info(f"[엑셀 파싱] 컬럼: {df.columns.tolist()}")
    except Exception as e:
        logger.warning(f"엑셀 파일 읽기 실패: {e}")
        return "엑셀 파일 읽기 실패"

    saved_count = 0
    row_count = len(df)
    logger.info(f"총 {row_count}행 (Header 제외)")

    # 헬퍼 함수들
    def parse_excel_date(raw):
        if raw is None or pd.isna(raw):
            return None
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, (int, float)):
            raw = str(int(raw))
        if isinstance(raw, str):
            raw = raw.strip()
            if len(raw) == 8 and raw.isdigit():
                try:
                    return datetime.strptime(raw, "%Y%m%d").date()
                except:
                    pass
            for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
                try:
                    return datetime.strptime(raw, fmt).date()
                except:
                    pass
            try:
                return datetime.strptime(raw, "%Y년 %m월 %d일").date()
            except:
                pass
        return None

    def to_str(val):
        if pd.isna(val):
            return ""
        return str(val).strip()

    def to_int(val):
        if pd.isna(val):
            return 0
        try:
            return int(val)
        except:
            return 0

    def to_decimal(val):
        if pd.isna(val):
            return Decimal("0.00")
        if isinstance(val, str):
            val = val.strip().replace(",", "").replace("%", "")
        try:
            return Decimal(str(val))
        except:
            return Decimal("0.00")

    def parse_percent(val):
        if pd.isna(val):
            return Decimal("0.00")
        if isinstance(val, str):
            tmp = val.strip().replace("%", "").replace(",", "")
            if not tmp:
                return Decimal("0.00")
            try:
                return Decimal(tmp)
            except:
                return Decimal("0.00")
        try:
            return Decimal(str(val))
        except:
            return Decimal("0.00")

    def split_product_option(full_name_str):
        if not full_name_str:
            return ("", "")
        parts = full_name_str.split(",", 1)
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
        else:
            return (full_name_str.strip(), "")

    for i, row in df.iterrows():
        if row.isna().all():
            logger.debug(f"Row {i}: 전체 NaN → 스킵")
            continue

        logger.debug(f"Row {i} 원본: {row.to_dict()}")

        raw_date = row.get("날짜", None)
        parsed_date = parse_excel_date(raw_date)
        if not parsed_date:
            logger.debug(f"Row {i}: 날짜 파싱 실패(raw_date={raw_date}) → 스킵")
            continue

        ad_type_val = to_str(row.get("광고유형", ""))
        campaign_id_val = to_str(row.get("캠페인 ID", ""))
        campaign_name_val = to_str(row.get("캠페인명", ""))
        ad_group_val = to_str(row.get("광고그룹", ""))

        executed_product_name_val = to_str(row.get("광고집행 상품명", ""))
        product_name_val, option_name_val = split_product_option(executed_product_name_val)
        executed_option_id_val = to_str(row.get("광고집행 옵션ID", ""))

        converting_product_name_val = to_str(row.get("광고전환매출발생 상품명", ""))
        converting_option_id_val = to_str(row.get("광고전환매출발생 옵션ID", ""))
        ad_placement_val = to_str(row.get("광고 노출 지면", ""))

        impressions_val = to_int(row.get("노출수", 0))
        clicks_val = to_int(row.get("클릭수", 0))
        ad_spend_val = to_decimal(row.get("광고비", 0))
        ctr_val = parse_percent(row.get("클릭률", "0"))
        orders_val = to_int(row.get("총 주문수(1일)", 0))
        sold_qty_val = to_int(row.get("총 판매수량(1일)", 0))
        sales_amt_val = to_decimal(row.get("총 전환매출액(1일)", 0))
        roas_val = to_decimal(row.get("총광고수익률(1일)", 0))

        # 명시적으로 Decimal 타입으로 강제 변환 (이미 Decimal일 경우 영향 없음)
        ad_spend_val = Decimal(ad_spend_val)
        ctr_val = Decimal(ctr_val)
        sales_amt_val = Decimal(sales_amt_val)
        roas_val = Decimal(roas_val)

        logger.debug(
            f"Row {i}: date={parsed_date}, ad_type={ad_type_val}, "
            f"campaign_id={campaign_id_val}, campaign_name={campaign_name_val}, "
            f"impressions={impressions_val}, clicks={clicks_val}, "
            f"ad_spend={ad_spend_val}({type(ad_spend_val)}), ctr={ctr_val}({type(ctr_val)}), "
            f"orders={orders_val}, sold_qty={sold_qty_val}, sales_amt={sales_amt_val}({type(sales_amt_val)}), "
            f"roas={roas_val}({type(roas_val)})"
        )

        try:
            rec = CoupangAdsReport(
                date=parsed_date,
                ad_type=ad_type_val,
                campaign_id=campaign_id_val,
                campaign_name=campaign_name_val,
                ad_group=ad_group_val,
                executed_product_name=executed_product_name_val,
                product_name=product_name_val,
                option_name=option_name_val,
                executed_option_id=executed_option_id_val,
                converting_product_name=converting_product_name_val,
                converting_option_id=converting_option_id_val,
                ad_placement=ad_placement_val,
                impressions=impressions_val,
                clicks=clicks_val,
                ad_spend=ad_spend_val,
                ctr=ctr_val,
                orders=orders_val,
                sold_quantity=sold_qty_val,
                sales_amount=sales_amt_val,
                roas=roas_val
            )
            rec.save()
            saved_count += 1
        except Exception as ex:
            logger.warning(f"Row {i} DB 저장 실패: {ex}")

    logger.info(f"AdsReport 저장 완료: {saved_count}건")
    os.remove(file_path)
    logger.info(f"파일 처리 완료 후 삭제: {os.path.basename(file_path)}")
    return "파일 처리 완료"


def upload_ads_excel_view(request):
    """
    광고 리포트 엑셀 업로드 폼을 렌더링하거나, 업로드된 파일들을 처리하는 뷰.
    POST 요청 시 업로드된 파일들을 임시 디렉토리에 저장 후, ads_excel_file 함수를 각 파일에 대해 호출하고,
    모든 파일 처리 후, 'ad_report' URL로 리다이렉트합니다.
    """
    if request.method == 'POST':
        excel_files = request.FILES.getlist('excel_file')
        if not excel_files:
            return HttpResponse("업로드된 파일이 없습니다.")
        tmp_dir = os.path.join(settings.BASE_DIR, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        messages = []
        for excel_file in excel_files:
            file_path = os.path.join(tmp_dir, excel_file.name)
            with open(file_path, 'wb') as f:
                for chunk in excel_file.chunks():
                    f.write(chunk)
            result = ads_excel_file(file_path)
            messages.append(f"{excel_file.name}: {result}")
        # 결과 메시지를 세션이나 쿼리 파라미터로 전달해도 좋습니다.
        # 여기서는 간단히 ad_report 페이지로 리다이렉트합니다.
        # 필요시 messages 내용을 로그나 세션에 저장할 수 있습니다.
        return redirect('ad_report')
    else:
        return render(request, 'sales_management/ad-report.html')    
    
#순수익 리포트 시작






# 헬퍼 함수: 딕셔너리의 모든 키를 문자열로 변환
def convert_keys(obj):
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            new_key = str(k)
            new_dict[new_key] = convert_keys(v)
        return new_dict
    elif isinstance(obj, list):
        return [convert_keys(item) for item in obj]
    else:
        return obj

def profit_report_view(request):
    """
    순수익 리포트:
      - 설정된 전체 기간의 데이터를 한 번만 가져와서,
        (1) 일자별 통계/소계를 생성하고,
        (2) 일자별 집계의 하위행(배송라벨별 detail)을 모아서 전체 기간의 라벨별 합계를 생성한다.
      - 모달에서는 일자별과 동일하게, 전체 기간 행의 토글 시 배송라벨(예: 로켓그로스, 판매자배송)별 상세 데이터가 표시된다.
      - 추가 요구사항:
        (3) 전체 기간 상품 집계를 기반으로
            마진이 -1% 이하인 상품,
            순수익이 +1만원(10000원) 이상인 상품,
            순수익이 -1만원(-10000원) 이하인 상품
            3개 목록을 만들어 프론트에 전달한다.
    """
    from datetime import date, datetime, timedelta
    from collections import defaultdict, OrderedDict
    import json
    from django.db.models import Sum
    from django.shortcuts import render
    from sales_management.models import CoupangDailySales, CoupangAdsReport, PurchaseCost

    # 1) 날짜 범위 파싱
    start_str = request.GET.get('start_date', '')
    end_str = request.GET.get('end_date', '')
    if not start_str or not end_str:
        start_d = date.today() - timedelta(days=14)
        end_d = date.today() - timedelta(days=1)
    else:
        try:
            start_d = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_d = datetime.strptime(end_str, "%Y-%m-%d").date()
        except ValueError:
            start_d = date.today() - timedelta(days=14)
            end_d = date.today() - timedelta(days=1)

    # ---------------------------
    # (A) 일자별 통계(요약) 집계
    daily_qs = (
        CoupangDailySales.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'sku_id', 'delivery_label', 'product_name', 'option_name')
        .annotate(
            sold_items=Sum('net_sold_items'),
            total_tx=Sum('total_transaction_amount'),
            net_sales=Sum('net_sales_amount')
        )
    )
    from collections import defaultdict
    daily_map = defaultdict(lambda: {
        "sold_items": 0,
        "total_tx": 0,
        "net_sales": 0,
        "purchase_cost": 0,
        "etc_cost": 0,  # 기타비용(배송비 등)
    })
    daily_sku_label = {}

    for row in daily_qs:
        d = row["date"]
        sku_str = str(row["sku_id"])
        label = row["delivery_label"] if row["delivery_label"] else ""
        sold_qty = row["sold_items"] or 0
        total_tx = row["total_tx"] or 0
        net_s = row["net_sales"] or 0

        # 매입가, 배송비 가져오기
        try:
            cost_obj = PurchaseCost.objects.get(sku_id=sku_str)
            unit_price = cost_obj.purchasing_price
            # 추가: 옵션코드를 사용해서 CostModel에서 배송비를 가져옴
            try:
                from sales_management.models import CostModel
                cost_model = CostModel.objects.get(option_code=cost_obj.option_code)
                ship_cost = cost_model.shipping_cost
            except CostModel.DoesNotExist:
                ship_cost = 0
        except PurchaseCost.DoesNotExist:
            unit_price = 0
            ship_cost = 0

        partial_cost = unit_price * sold_qty
        additional_cost = ship_cost * sold_qty  # 배송비를 기타비용으로 처리

        daily_map[(d, label)]["sold_items"] += sold_qty
        daily_map[(d, label)]["total_tx"] += total_tx
        daily_map[(d, label)]["net_sales"] += net_s
        daily_map[(d, label)]["purchase_cost"] += partial_cost
        daily_map[(d, label)]["etc_cost"] += additional_cost

        daily_sku_label[(d, sku_str)] = label

    # 광고 데이터 집계 (일자별)
    from sales_management.models import CoupangAdsReport
    ads_qs = (
        CoupangAdsReport.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'executed_option_id')
        .annotate(
            ad_sold=Sum('sold_quantity'),
            orders_sum=Sum('orders'),
            clicks_sum=Sum('clicks'),
            ad_spend=Sum('ad_spend'),
            ad_rev=Sum('sales_amount')
        )
    )
    ads_map = defaultdict(lambda: {
        "ad_sold": 0, "orders": 0, "clicks": 0, "ad_spend": 0, "ad_rev": 0
    })

    for ad in ads_qs:
        d = ad["date"]
        sku_str = str(ad["executed_option_id"])
        if (d, sku_str) in daily_sku_label:
            label = daily_sku_label[(d, sku_str)]
        else:
            continue
        ads_map[(d, label)]["ad_sold"] += ad["ad_sold"] or 0
        ads_map[(d, label)]["orders"] += ad["orders_sum"] or 0
        ads_map[(d, label)]["clicks"] += ad["clicks_sum"] or 0
        ads_map[(d, label)]["ad_spend"] += ad["ad_spend"] or 0
        ads_map[(d, label)]["ad_rev"] += ad["ad_rev"] or 0

    # 날짜별, 라벨별 결합 -> date_label_map는 {날짜: {라벨: 데이터}} 구조
    date_label_map = defaultdict(dict)
    all_keys = set(daily_map.keys()) | set(ads_map.keys())
    for (d, lbl) in all_keys:
        sold_part = daily_map[(d, lbl)]
        ad_part = ads_map[(d, lbl)]
        sold_qty = sold_part["sold_items"]
        net_s = sold_part["net_sales"]
        purchase_c = sold_part["purchase_cost"]
        etc_cost = sold_part["etc_cost"]  # 배송비 등 기타비용
        ad_sp = ad_part["ad_spend"]
        commission = net_s * 0.1188
        profit_val = net_s - commission - ad_sp - purchase_c - etc_cost
        margin_rate = (profit_val / net_s) * 100 if net_s > 0 else 0
        clicks = ad_part["clicks"]
        orders = ad_part["orders"]
        conv = (orders / clicks) * 100 if clicks > 0 else 0

        date_label_map[d][lbl] = {
            "kind": lbl,
            "qty": sold_qty,
            "ad_qty": ad_part["ad_sold"],
            "net_sales_amount": net_s,
            "commission": commission,
            "ad_spend": ad_sp,
            "purchase_cost": purchase_c,
            "etc_cost": etc_cost,
            "profit": profit_val,
            "margin_rate": margin_rate,
            "conversion_rate": conv
        }

    # 일자별 리포트 생성
    daily_reports = []
    sorted_dates = sorted(date_label_map.keys())
    for d in sorted_dates:
        label_map = date_label_map[d]
        if not label_map:
            continue

        sum_qty = sum(data["qty"] for data in label_map.values())
        sum_ad_qty = sum(data["ad_qty"] for data in label_map.values())
        sum_net = sum(data["net_sales_amount"] for data in label_map.values())
        sum_commission = sum(data["commission"] for data in label_map.values())
        sum_ad_spend = sum(data["ad_spend"] for data in label_map.values())
        sum_purchase = sum(data["purchase_cost"] for data in label_map.values())
        sum_etc = sum(data["etc_cost"] for data in label_map.values())
        sum_profit = sum(data["profit"] for data in label_map.values())
        day_margin = (sum_profit / sum_net * 100) if sum_net > 0 else 0
        conv_list = [data.get("conversion_rate", 0) for data in label_map.values()]
        day_conv = (sum(conv_list) / len(conv_list)) if conv_list else 0

        if (sum_qty == 0 and sum_ad_qty == 0 and sum_net == 0 and
            sum_commission == 0 and sum_ad_spend == 0 and sum_purchase == 0 and
            sum_etc == 0 and sum_profit == 0):
            continue

        details_list = []
        for lbl, data in label_map.items():
            details_list.append({
                "kind": lbl,
                "qty": data["qty"],
                "ad_qty": data["ad_qty"],
                "net_sales_amount": data["net_sales_amount"],
                "commission": data["commission"],
                "ad_spend": data["ad_spend"],
                "purchase_cost": data["purchase_cost"],
                "etc_cost": data["etc_cost"],
                "profit": data["profit"],
                "margin_rate": data["margin_rate"],
                "conversion_rate": data.get("conversion_rate", 0)
            })

        daily_reports.append({
            "date_str": d.strftime("%Y-%m-%d"),
            "qty": sum_qty,
            "ad_qty": sum_ad_qty,
            "net_sales_amount": sum_net,
            "commission": sum_commission,
            "ad_spend": sum_ad_spend,
            "purchase_cost": sum_purchase,
            "etc_cost": sum_etc,
            "profit": sum_profit,
            "margin_rate": day_margin,
            "conversion_rate": day_conv,
            "details": details_list
        })

    # (B) 전체 기간 합계 (Period Summary) 계산 (일자별 리포트 기반)
    sum_dict = {
        "total_qty": 0,
        "total_ad_qty": 0,
        "net_sales_amount": 0,
        "commission": 0,
        "ad_spend": 0,
        "purchase_cost": 0,
        "etc_cost": 0,
        "profit": 0,
    }
    for day in daily_reports:
        sum_dict["total_qty"] += day["qty"]
        sum_dict["total_ad_qty"] += day["ad_qty"]
        sum_dict["net_sales_amount"] += day["net_sales_amount"]
        sum_dict["commission"] += day["commission"]
        sum_dict["ad_spend"] += day["ad_spend"]
        sum_dict["purchase_cost"] += day["purchase_cost"]
        sum_dict["etc_cost"] += day["etc_cost"]
        sum_dict["profit"] += day["profit"]

    # 전체 기간 마진률
    overall_margin_rate = (
        (sum_dict["profit"] / sum_dict["net_sales_amount"]) * 100
        if sum_dict["net_sales_amount"] > 0 else 0
    )
    period_summary = {
        "total_qty": sum_dict["total_qty"],
        "total_ad_qty": sum_dict["total_ad_qty"],
        "net_sales_amount": sum_dict["net_sales_amount"],
        "commission": sum_dict["commission"],
        "ad_spend": sum_dict["ad_spend"],
        "purchase_cost": sum_dict["purchase_cost"],
        "etc_cost": sum_dict["etc_cost"],
        "profit": sum_dict["profit"],
        "margin_rate": overall_margin_rate
    }

    # ---------------------------
    # (F) 매입가 확인용 데이터: 해당 기간 내 PurchaseCost.purchasing_price가 0인 옵션들
    zero_purchase_list = []
    zero_costs = PurchaseCost.objects.filter(purchasing_price=0)
    for pc in zero_costs:
        # CoupangDailySales에서 SKU ID 기준으로 해당 항목을 찾음
        item = CoupangDailySales.objects.filter(sku_id=pc.sku_id).first()
        if item:
            zero_purchase_list.append({
                "product_name": item.product_name or "(상품명없음)",
                "option_name": item.option_name or "(옵션없음)",
                "option_code": pc.option_code,
                "purchasing_price": pc.purchasing_price,
            })

    # ---------------------------
    # (C) 전체 기간 상세 집계 (일자별 리포트의 하위행 detail)을 모아서 라벨별로 합산
    period_details_final = {}
    for day in daily_reports:
        for detail in day["details"]:
            kind = detail["kind"]
            if kind not in period_details_final:
                period_details_final[kind] = detail.copy()
                period_details_final[kind]["_count"] = 1
            else:
                for field in [
                    "qty", "ad_qty", "net_sales_amount", "commission",
                    "ad_spend", "purchase_cost", "etc_cost", "profit"
                ]:
                    period_details_final[kind][field] += detail[field]
                period_details_final[kind]["conversion_rate"] += detail.get("conversion_rate", 0)
                period_details_final[kind]["_count"] += 1

    for kind, agg in period_details_final.items():
        net_sales = agg["net_sales_amount"]
        if net_sales > 0:
            agg["margin_rate"] = (agg["profit"] / net_sales) * 100
        else:
            agg["margin_rate"] = 0
        agg["conversion_rate"] = (
            agg["conversion_rate"] / agg["_count"] if agg["_count"] > 0 else 0
        )
        del agg["_count"]

    # ---------------------------
    # (D) 전체 기간/일자별 상품/옵션 집계 (모달용)
    # (B-1) 일자별 상품/옵션 집계 (모달용)
    sales_qs = (
        CoupangDailySales.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'sku_id', 'displayed_product_id', 'product_name', 'option_name', 'delivery_label')
        .annotate(
            sold_qty=Sum('net_sold_items'),
            net_sales=Sum('net_sales_amount'),
        )
    )
    ads_qs_2 = (
        CoupangAdsReport.objects
        .filter(date__range=[start_d, end_d])
        .values('date', 'executed_option_id')
        .annotate(
            ad_sold=Sum('sold_quantity'),
            ad_spend=Sum('ad_spend'),
        )
    )
    sales_data = list(sales_qs)
    ads_data = list(ads_qs_2)

    day_p_o_map = defaultdict(lambda: {
        "sold_qty": 0, "net_sales": 0, "purchase_cost": 0, "ad_sold": 0, "ad_spend": 0
    })
    sku_mapping = {}           # sku -> (date, disp_id, option_name, label)
    product_name_mapping = {}  # (date, disp_id) -> product_name

    for row in sales_data:
        d = row["date"].strftime("%Y-%m-%d")
        disp_id = row["displayed_product_id"]
        p_name = row["product_name"] or "(상품명없음)"
        o_name = row["option_name"] or "(옵션없음)"
        label = row["delivery_label"] if row["delivery_label"] else ""
        key = (d, disp_id, o_name, label)
        sku = str(row["sku_id"])

        sku_mapping[sku] = (d, disp_id, o_name, label)
        product_name_mapping[(d, disp_id)] = p_name

        sold_qty = row["sold_qty"] or 0
        net_sales = row["net_sales"] or 0

        try:
            cost_obj = PurchaseCost.objects.get(sku_id=sku)
            purchase_c = cost_obj.purchasing_price * sold_qty
        except PurchaseCost.DoesNotExist:
            purchase_c = 0

        day_p_o_map[key]["sold_qty"] += sold_qty
        day_p_o_map[key]["net_sales"] += net_sales
        day_p_o_map[key]["purchase_cost"] += purchase_c

    for ad_row in ads_data:
        d = ad_row["date"].strftime("%Y-%m-%d")
        sku = str(ad_row["executed_option_id"])
        if sku not in sku_mapping:
            continue
        d2, disp_id, o_name, label = sku_mapping[sku]
        key = (d, disp_id, o_name, label)
        ad_sold = ad_row["ad_sold"] or 0
        ad_spend = ad_row["ad_spend"] or 0
        day_p_o_map[key]["ad_sold"] += ad_sold
        day_p_o_map[key]["ad_spend"] += ad_spend

    from collections import OrderedDict
    day_products_map = defaultdict(lambda: OrderedDict())
    for (d, disp_id, o_name, label), vals in day_p_o_map.items():
        sold_qty = vals["sold_qty"]
        net_sales = vals["net_sales"]
        purchase_c = vals["purchase_cost"]
        ad_sold = vals.get("ad_sold", 0)
        ad_spend = vals.get("ad_spend", 0)

        commission = net_sales * 0.1188
        profit = net_sales - commission - ad_spend - purchase_c
        margin_rate = (profit / net_sales * 100) if net_sales > 0 else 0

        prod_key = (d, disp_id, label)
        if prod_key not in day_products_map[d]:
            day_products_map[d][prod_key] = {
                "product_name": product_name_mapping.get((d, disp_id), "(상품명없음)"),
                "qty": 0,
                "ad_qty": 0,
                "net_sales_amount": 0,
                "ad_spend": 0,
                "purchase_cost": 0,
                "commission": 0,
                "profit": 0,
                "margin_rate": 0,
                "options": []
            }
        opt_dict = {
            "option_name": o_name,
            "qty": sold_qty,
            "ad_qty": ad_sold,
            "net_sales_amount": net_sales,
            "purchase_cost": purchase_c,
            "ad_spend": ad_spend,
            "commission": commission,
            "profit": profit,
            "margin_rate": margin_rate,
            "label": label
        }
        day_products_map[d][prod_key]["options"].append(opt_dict)

    # (B-2) 전체 기간 상품/옵션 집계 (모달용)
    period_p_o_map = defaultdict(lambda: {
        "sold_qty": 0, "net_sales": 0, "purchase_cost": 0, "ad_sold": 0, "ad_spend": 0
    })
    period_sku_mapping = {}
    period_product_name_mapping = {}

    for row in sales_data:
        disp_id = row["displayed_product_id"]
        p_name = row["product_name"] or "(상품명없음)"
        o_name = row["option_name"] or "(옵션없음)"
        label = row["delivery_label"] if row["delivery_label"] else ""
        sku = str(row["sku_id"])
        period_sku_mapping[sku] = (disp_id, o_name, label)
        period_product_name_mapping[disp_id] = p_name

        sold_qty = row["sold_qty"] or 0
        net_sales = row["net_sales"] or 0

        try:
            cost_obj = PurchaseCost.objects.get(sku_id=sku)
            purchase_c = cost_obj.purchasing_price * sold_qty
        except PurchaseCost.DoesNotExist:
            purchase_c = 0

        key = (disp_id, o_name, label)
        period_p_o_map[key]["sold_qty"] += sold_qty
        period_p_o_map[key]["net_sales"] += net_sales
        period_p_o_map[key]["purchase_cost"] += purchase_c

    for ad_row in ads_data:
        sku = str(ad_row["executed_option_id"])
        if sku not in period_sku_mapping:
            continue
        disp_id, o_name, label = period_sku_mapping[sku]
        key = (disp_id, o_name, label)
        ad_sold = ad_row["ad_sold"] or 0
        ad_spend = ad_row["ad_spend"] or 0
        period_p_o_map[key]["ad_sold"] += ad_sold
        period_p_o_map[key]["ad_spend"] += ad_spend

    period_products_map = OrderedDict()
    for (disp_id, o_name, label), vals in period_p_o_map.items():
        sold_qty = vals["sold_qty"]
        net_sales = vals["net_sales"]
        purchase_c = vals["purchase_cost"]
        ad_sold = vals.get("ad_sold", 0)
        ad_spend = vals.get("ad_spend", 0)

        commission = net_sales * 0.1188
        profit = net_sales - commission - ad_spend - purchase_c
        margin_rate = (profit / net_sales * 100) if net_sales > 0 else 0

        prod_key = f"{disp_id}_{label}"
        if prod_key not in period_products_map:
            period_products_map[prod_key] = {
                "product_name": period_product_name_mapping.get(disp_id, "(상품명없음)"),
                "qty": 0,
                "ad_qty": 0,
                "net_sales_amount": 0,
                "ad_spend": 0,
                "purchase_cost": 0,
                "commission": 0,
                "profit": 0,
                "margin_rate": 0,
                "options": []
            }
        option_dict = {
            "option_name": o_name,
            "qty": sold_qty,
            "ad_qty": ad_sold,
            "net_sales_amount": net_sales,
            "purchase_cost": purchase_c,
            "ad_spend": ad_spend,
            "commission": commission,
            "profit": profit,
            "margin_rate": margin_rate,
            "label": label
        }
        period_products_map[prod_key]["options"].append(option_dict)

    # 옵션들 합산 (일자별)
    for d in list(day_products_map.keys()):
        for prod_key in list(day_products_map[d].keys()):
            pinfo = day_products_map[d][prod_key]
            pinfo["options"] = [
                opt for opt in pinfo["options"]
                if not (opt["qty"] == 0 and opt["ad_qty"] == 0 and opt["net_sales_amount"] == 0 and
                        opt["ad_spend"] == 0 and opt["purchase_cost"] == 0 and opt["profit"] == 0)
            ]
            if not pinfo["options"]:
                del day_products_map[d][prod_key]
            else:
                sum_qty = sum(opt["qty"] for opt in pinfo["options"])
                sum_ad_qty = sum(opt["ad_qty"] for opt in pinfo["options"])
                sum_net = sum(opt["net_sales_amount"] for opt in pinfo["options"])
                sum_adspend = sum(opt["ad_spend"] for opt in pinfo["options"])
                sum_pc = sum(opt["purchase_cost"] for opt in pinfo["options"])

                commission = sum_net * 0.1188
                profit_val = sum_net - commission - sum_adspend - sum_pc
                margin_rate = (profit_val / sum_net * 100) if sum_net > 0 else 0

                pinfo["qty"] = sum_qty
                pinfo["ad_qty"] = sum_ad_qty
                pinfo["net_sales_amount"] = sum_net
                pinfo["ad_spend"] = sum_adspend
                pinfo["purchase_cost"] = sum_pc
                pinfo["commission"] = commission
                pinfo["profit"] = profit_val
                pinfo["margin_rate"] = margin_rate

    # 옵션들 합산 (전체 기간)
    for prod_key in list(period_products_map.keys()):
        pinfo = period_products_map[prod_key]
        pinfo["options"] = [
            opt for opt in pinfo["options"]
            if not (opt["qty"] == 0 and opt["ad_qty"] == 0 and opt["net_sales_amount"] == 0 and
                    opt["ad_spend"] == 0 and opt["purchase_cost"] == 0 and opt["profit"] == 0)
        ]
        if not pinfo["options"]:
            del period_products_map[prod_key]
        else:
            sum_qty = sum(opt["qty"] for opt in pinfo["options"])
            sum_ad_qty = sum(opt["ad_qty"] for opt in pinfo["options"])
            sum_net = sum(opt["net_sales_amount"] for opt in pinfo["options"])
            sum_adspend = sum(opt["ad_spend"] for opt in pinfo["options"])
            sum_pc = sum(opt["purchase_cost"] for opt in pinfo["options"])

            commission = sum_net * 0.1188
            profit_val = sum_net - commission - sum_adspend - sum_pc
            margin_rate = (profit_val / sum_net * 100) if sum_net > 0 else 0

            pinfo["qty"] = sum_qty
            pinfo["ad_qty"] = sum_ad_qty
            pinfo["net_sales_amount"] = sum_net
            pinfo["ad_spend"] = sum_adspend
            pinfo["purchase_cost"] = sum_pc
            pinfo["commission"] = commission
            pinfo["profit"] = profit_val
            pinfo["margin_rate"] = margin_rate

    # JSON 변환 (모달용)
    # convert_keys 함수가 이미 있다고 가정
    day_products_map_json = json.dumps(convert_keys(day_products_map), ensure_ascii=False, default=str)
    period_products_map_json = json.dumps(convert_keys(period_products_map), ensure_ascii=False, default=str)

    # -------------------------------------------------------------------------
    # **(G) KPI 3종 추출**: period_products_map에 상품별 집계가 있으므로, 이걸 이용해 필터링
    #
    # period_products_map: {
    #    "<disp_id>_<label>": {
    #       "product_name": ...,
    #       "qty": ...,
    #       "ad_qty": ...,
    #       "net_sales_amount": ...,
    #       "ad_spend": ...,
    #       "purchase_cost": ...,
    #       "commission": ...,
    #       "profit": ...,
    #       "margin_rate": ...,
    #       "options": [...]
    #    },
    #    ...
    # }

    kpi_list = []
    for prod_key, pinfo in period_products_map.items():
        # 여러 옵션(label)이라도 일단 첫 번째 옵션의 배송라벨을 kind로 표시 (혹은 필요에 따라 key에서 파싱)
        kind = ""
        if pinfo["options"]:
            kind = pinfo["options"][0].get("label", "")

        kpi_list.append({
            "product_name": pinfo["product_name"],
            "kind": kind,  # 배송라벨(판매자배송/로켓 등)을 그대로 표시하겠다면 이렇게 매핑
            "qty": pinfo["qty"],
            "ad_qty": pinfo["ad_qty"],
            "net_sales_amount": pinfo["net_sales_amount"],
            "ad_spend": pinfo["ad_spend"],
            "purchase_cost": pinfo["purchase_cost"],
            "profit": pinfo["profit"],
            "margin_rate": pinfo["margin_rate"],
        })

    # 마진이 -1% 이하인 상품
    kpi_margin_low = [x for x in kpi_list if x["margin_rate"] <= -1]
    # 순수익이 +1만원(10000원) 이상
    kpi_profit_high = [x for x in kpi_list if x["profit"] >= 10000]
    # 순수익이 -1만원(-10000원) 이하
    kpi_profit_low = [x for x in kpi_list if x["profit"] <= -10000]

    # ---------------------------
    # (E) 컨텍스트 구성 및 렌더링
    context = {
        "start_date": start_d,
        "end_date": end_d,
        "daily_reports": daily_reports,                 # 일자별 요약 테이블
        "period_summary": period_summary,               # 전체 기간 합계
        "day_products_map_json": day_products_map_json, # 일자별 상품/옵션 상세 (모달용)
        "period_details": period_details_final,         # 전체 기간 상세 (배송라벨별 합산)
        "period_products_map_json": period_products_map_json,  # 전체 기간 상품/옵션 상세 (모달용)
        "zero_purchase_list": zero_purchase_list,        # 매입가 0인 옵션 리스트

        # (G) 추가된 KPI 세트
        "kpi_margin_low": kpi_margin_low,
        "kpi_profit_high": kpi_profit_high,
        "kpi_profit_low": kpi_profit_low,
    }
    return render(request, "sales_management/profit_report.html", context)



@require_POST
def update_costs_from_seller_tool_view(request):
    """
    1) CoupangItem: rocket_external_vendor_sku + marketplace_external_vendor_sku -> option_codes
    2) 셀러툴 API -> (option_code -> totalPurchasePrice) mapping
    3) 다시 CoupangItem 순회:
       - rocket: sku_id=rocket_vendor_item_id, option_code=rocket_external_vendor_sku
       - market: sku_id=marketplace_vendor_item_id, option_code=marketplace_external_vendor_sku
       -> PurchaseCost 저장
    """
    try:
        # (A) 옵션코드 수집
        option_codes = set()
        items = CoupangItem.objects.all()
        for it in items:
            if it.rocket_external_vendor_sku:
                option_codes.add(it.rocket_external_vendor_sku)
            if it.marketplace_external_vendor_sku:
                option_codes.add(it.marketplace_external_vendor_sku)

        option_codes = list(option_codes)
        logger.info(f"[update_costs_from_seller_tool_view] option_codes 개수={len(option_codes)}")
        if not option_codes:
            messages.warning(request, "옵션코드가 없습니다.")
            return redirect('profit_report')

        # (B) 셀러툴 API
        result_data = fetch_seller_tool_option_info(option_codes)
        content_list = result_data.get("content", [])
        logger.info(f"[update_costs_from_seller_tool_view] content_list len={len(content_list)}")

        # (B-1) dict
        code_to_price = {}
        for row in content_list:
            c = row.get("code")
            p = row.get("totalPurchasePrice", 0)
            if c:
                code_to_price[c] = p

        updated_count = 0
        created_count = 0

        # (C) CoupangItem 순회, rocket + market 분기
        for it in items:
            # rocket
            if it.rocket_vendor_item_id and it.rocket_external_vendor_sku:
                sku_id_val = it.rocket_vendor_item_id
                option_code_val = it.rocket_external_vendor_sku
                purchase_val = code_to_price.get(option_code_val, 0)

                obj, created_flag = PurchaseCost.objects.update_or_create(
                    sku_id=sku_id_val,
                    option_code=option_code_val,
                    defaults={
                        "purchasing_price": purchase_val
                    }
                )
                if created_flag:
                    created_count += 1
                    logger.info(f"NEW(rocket): sku_id={sku_id_val}, opt={option_code_val}, price={purchase_val}")
                else:
                    updated_count += 1
                    logger.info(f"UPD(rocket): sku_id={sku_id_val}, opt={option_code_val}, price={purchase_val}")

            # market
            if it.marketplace_vendor_item_id and it.marketplace_external_vendor_sku:
                sku_id_val = it.marketplace_vendor_item_id
                option_code_val = it.marketplace_external_vendor_sku
                purchase_val = code_to_price.get(option_code_val, 0)

                obj, created_flag = PurchaseCost.objects.update_or_create(
                    sku_id=sku_id_val,
                    option_code=option_code_val,
                    defaults={
                        "purchasing_price": purchase_val
                    }
                )
                if created_flag:
                    created_count += 1
                    logger.info(f"NEW(market): sku_id={sku_id_val}, opt={option_code_val}, price={purchase_val}")
                else:
                    updated_count += 1
                    logger.info(f"UPD(market): sku_id={sku_id_val}, opt={option_code_val}, price={purchase_val}")

        messages.success(request, f"매입가 업데이트 완료! (생성:{created_count}, 업데이트:{updated_count})")

    except Exception as e:
        logger.exception("[update_costs_from_seller_tool_view] 오류:")
        messages.error(request, f"에러 발생: {str(e)}")

    return redirect('profit_report')