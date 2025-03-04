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
from collections import defaultdict, OrderedDict  # 추가


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



@require_POST
def deleted_coupang_sales_view(request):
    start_str = request.POST.get('fetch_start_date')
    end_str = request.POST.get('fetch_end_date')
    logger.info(f"Received start date: {start_str}, end date: {end_str}")
    
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            count = CoupangDailySales.objects.filter(date__range=(start_date, end_date)).count()
            logger.info(f"Records before deletion: {count}")
            deleted_count, _ = CoupangDailySales.objects.filter(date__range=(start_date, end_date)).delete()
            messages.success(request, f"{start_str}부터 {end_str}까지 {deleted_count}건의 데이터가 삭제되었습니다.")
        except Exception as e:
            logger.exception("Deletion error:")
            messages.error(request, "날짜 형식이 올바르지 않거나 삭제 중 오류가 발생했습니다.")
    else:
        messages.warning(request, "날짜를 선택해주세요!")
    
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

def delete_ads_report(request):
    start_str = request.POST.get('fetch_start_date')
    end_str = request.POST.get('fetch_end_date')
    logger.info(f"Received start date: {start_str}, end date: {end_str}")
    
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            count = CoupangAdsReport.objects.filter(date__range=(start_date, end_date)).count()
            logger.info(f"Records before deletion: {count}")
            deleted_count, _ = CoupangAdsReport.objects.filter(date__range=(start_date, end_date)).delete()
            messages.success(request, f"{start_str}부터 {end_str}까지 {deleted_count}건의 데이터가 삭제되었습니다.")
        except Exception as e:
            logger.exception("Deletion error:")
            messages.error(request, "날짜 형식이 올바르지 않거나 삭제 중 오류가 발생했습니다.")
    else:
        messages.warning(request, "날짜를 선택해주세요!")
    
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
    sorted_dates = sorted(date_label_map.keys(),reverse=True)
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





#네이버 시작

import json
from collections import defaultdict
from django.http import JsonResponse
from django.shortcuts import render

from .api_clients import NAVER_ACCOUNTS, fetch_naver_products_with_details, fetch_naver_sales
from .models import naverItem, NaverDailySales,naverItem


def naver_product_list_view(request):
    from django.db.models import Q
    

    search_query = request.GET.get('search_query', '').strip()

    qs = naverItem.objects.all()
    if search_query:
        qs = qs.filter(
            Q(productID__icontains=search_query)
            | Q(skuID__icontains=search_query)
            | Q(itemName__icontains=search_query)
            | Q(option_name__icontains=search_query)
            | Q(optioncode__icontains=search_query)
            | Q(account_name__icontains=search_query)
            | Q(channelProductID__icontains=search_query)  # channel 상품ID로도 검색 가능하도록 추가
        ).distinct()

    total_count = qs.count()

    # (A) productID별로 grouped_data 구성
    grouped_data = {}
    for item in qs:
        pid = item.productID
        if pid not in grouped_data:
            grouped_data[pid] = {
                'channelProductID': item.channelProductID,  # 추가: 채널 상품 ID 정보 저장
                'items': []
            }
        grouped_data[pid]['items'].append(item)

    # (B) 여기서 **수수료 금액** 계산해서, 각 item에 임시 속성으로 추가
    #     수수료 금액 = sale_price * market_fee
    for pid, data_dict in grouped_data.items():
        for item_obj in data_dict['items']:
            # int로 반올림(원 단위). 필요하다면 math.floor/ceil/Decimal 등 추가 처리
            item_obj.calculated_fee = int(item_obj.sale_price * item_obj.market_fee)

    context = {
        'search_query': search_query,
        'total_count': total_count,
        'grouped_data': grouped_data,
    }
    return render(request, 'sales_management/naver_product_list.html', context)



def naver_update_products(request):
    """
    1) NAVER_ACCOUNTS에 등록된 모든 계정에 대해
       fetch_naver_products_with_details 로 전체 상품 + 옵션 정보를 가져온다.
    2) naverItem DB 테이블에 저장/갱신한다.
    """
    if request.method == 'POST':
        from django.contrib import messages
        # 전체 계정을 순회하며 상품 정보를 가져와 DB에 저장
        total_saved = 0
        for account_info in NAVER_ACCOUNTS:
            success, product_list = fetch_naver_products_with_details(account_info)
            if not success:
                # 실패 시 product_list는 에러 메시지
                messages.error(request, f"[{account_info['names']}] 네이버 상품 목록 조회 실패: {product_list}")
                continue  # 다른 계정들도 시도하기 위해 continue

            # DB 저장
            count_saved = save_naver_products_to_db(product_list, account_info)
            total_saved += count_saved

            messages.success(request, f"[{account_info['names']}] 상품 {count_saved}건 저장/갱신 완료.")

        messages.success(request, f"모든 계정 상품데이터 총 {total_saved}건 저장/갱신 완료.")
        return redirect('naver_product_list')

    else:
        # GET이면 그냥 리다이렉트
        return redirect('naver_product_list')



def save_naver_products_to_db(product_list, account_info):
    """
    네이버 상품 목록(product_list)을 받아 naverItem 모델에 저장/갱신한다.
    - product_list = [
        {
          "originProductNo": ...,
          "productName": ...,
          "representativeImage": ...,
          "salePrice": ...,
          "discountedPrice": ...,
          "stockQuantity": ...,
          "sellerCodeInfo": { "sellerManagerCode": ... },
          "optionCombinations": [
              { "id":..., "optionName1":..., "sellerManagerCode":..., "price":..., ... },
              ...
          ]
        }, ...
      ]
    """
    from .models import naverItem

    # 예: account_info['names'][0] 에 스토어명/브랜드명 등이 들어있다고 가정
    brand_name = account_info['names'][0] if 'names' in account_info else "(브랜드미지정)"
    
    count = 0
    
    for product in product_list:
        productID       = product.get("originProductNo")  # 상품ID
        channelProductID = product.get("channelProductNo", "")  # 채널상품ID
        productName     = product.get("productName")      # 상품명
        discountedPrice = product.get("discountedPrice", 0)  # 정가(할인가)
        
        option_combos   = product.get("optionCombinations") or []
        
        # 옵션 정보가 하나 이상 있으면, 옵션별로 저장
        if option_combos:
            for combo in option_combos:
                sku_id     = combo.get("id")                 # SKUID
                if not sku_id:
                    # sku_id가 없으면 건너뜀
                    continue
                
                optioncode = combo.get("sellerManagerCode", "")
                optionName = combo.get("optionName1", "")
                optionPrice= combo.get("price", 0)

                # (A) update_or_create 로 DB에 저장/갱신
                obj, created = naverItem.objects.update_or_create(
                    skuID=sku_id,  # unique 필드
                    defaults={
                        'productID': productID,
                        'channelProductID': channelProductID,
                        'optioncode': optioncode,
                        'delivery_label': "판매자배송",  # 고정
                        'itemName': productName,
                        'option_name': optionName,
                        'product_price': discountedPrice,
                        'option_price': optionPrice,
                        'account_name': brand_name,
                        'market_fee': 0.04,  # 4%
                        # sale_price와 profit은 model의 save()에서 자동 계산됨
                    }
                )
                count += 1

        else:
            # 만약 옵션이 전혀 없는 상품이라면 => 단일 상품으로 처리
            # 이때 skuID가 필요하다면 "originProductNo"로 대체하거나, 다른 고유값을 정해둬야 함
            # 예시로 skuID=originProductNo 로 처리:
            sku_id = productID
            obj, created = naverItem.objects.update_or_create(
                skuID=sku_id,
                defaults={
                    'productID': productID,
                    'channelProductID': channelProductID,
                    'optioncode': "",
                    'delivery_label': "판매자배송",
                    'itemName': productName,
                    'option_name': "",  # 옵션 없음
                    'product_price': discountedPrice,
                    'option_price': 0,
                    'account_name': brand_name,
                    'market_fee': 0.04,
                }
            )
            count += 1

    return count




def update_naver_option_list(request):
    """
    네이버 API로부터 상품/옵션 리스트를 받아, OutOfStock 모델에 매핑해서 업데이트한다.
    """
    account_name = request.GET.get("account_name", "").strip()
    if not account_name:
        return JsonResponse({"error": "account_name이 없습니다."}, status=400)

    # 1) 네이버 계정 찾기
    account_info = None
    for acct in NAVER_ACCOUNTS:
        if account_name in acct["names"]:
            account_info = acct
            break

    if not account_info:
        msg = f"[update_naver_option_list] 계정 '{account_name}'을 NAVER_ACCOUNTS에서 찾을 수 없습니다."
        logger.warning(msg)
        return JsonResponse({"error": msg}, status=400)

    # 2) 네이버 상품/옵션 목록 가져오기
    is_ok, detailed_list = fetch_naver_products_with_details(account_info)
    if not is_ok:
        logger.error(f"[update_naver_option_list] fetch fail: {detailed_list}")
        return JsonResponse({"error": "네이버 상품목록 조회 실패", "detail": detailed_list}, status=400)

    logger.debug(f"[update_naver_option_list] detailed_list count={len(detailed_list)}")

    # 업데이트된 OutOfStock 레코드(또는 생성된 레코드) 수
    updated_count = 0

    for prod_data in detailed_list:
        # 공통 영역(상품 레벨)
        origin_no      = prod_data.get("originProductNo")            # 상품ID
        rep_image_dict = prod_data.get("representativeImage", {})     # 대표이미지
        if isinstance(rep_image_dict, dict):
            rep_img_url = rep_image_dict.get("url", "")
        else:
            rep_img_url = ""

        # 네이버에서 사용하는 '정가(salePrice)'와 '할인가(discountedPrice)'
        naver_sale_price       = prod_data.get("salePrice", 0)        # 정가
        naver_discounted_price = prod_data.get("discountedPrice", 0)  # 할인가
        product_name           = prod_data.get("productName", "")     # 주문상품명(주문 시 노출되는 상품명)

        # (옵션 목록 파싱)
        option_combos = prod_data.get("optionCombinations", [])
        if not option_combos:
            # 옵션이 없는 단일상품인 경우도 처리 가능
            # 여기서는 단일상품이라면 option_id를 임의로 처리하거나 생략할 수 있습니다.
            # 예시) option_id를 origin_no 로 대체
            single_option_id_stock = prod_data.get("stockQuantity", 0)

            _, created = OutOfStock.objects.update_or_create(
                option_id=str(origin_no),  # 옵션ID가 꼭 있어야 unique한 항목이므로
                defaults={
                    "platform_name":          account_name,     # 플랫폼명
                    "representative_image":   rep_img_url,      # 대표이미지
                    "product_id":             origin_no,        # 상품ID
                    "option_id_stock":        single_option_id_stock,
                    "expected_restock_date":  None,             # API상 별도 필드가 없으므로 None
                    "order_product_name":     product_name,
                    "order_option_name_01":   "",               # 단일상품이므로 옵션명 비어있음
                    "order_option_name_02":   "",               # 단일상품이므로 옵션명 비어있음
                    "option_code":            "",               # 단일상품이므로 (or sellerManagerCode가 없으므로)
                    "original_price":         naver_sale_price,
                    "sale_price":             naver_discounted_price,
                    "add_option_price":       0,                # 단일상품이라 추가옵션가 없음
                    # out_of_stock_at, updated_at 은 자동 or 상황에 따라 세팅
                }
            )
            updated_count += 1
            continue

        # 옵션이 여러 개 존재하는 경우
        for combo in option_combos:
            opt_id      = combo.get("id")                     # 옵션ID
            opt_stk     = combo.get("stockQuantity", 0)       # 옵션ID재고
            opt_name1   = combo.get("optionName1", "")        # 주문옵션명01
            opt_name2   = combo.get("optionName2", "")        # 주문옵션명02
            opt_code    = combo.get("sellerManagerCode", "")  # 옵션코드
            add_opt_prc = combo.get("price", 0)               # 추가옵션가

            # OutOfStock 업데이트 (option_id 가 unique)
            _, created = OutOfStock.objects.update_or_create(
                option_id=str(opt_id),  # 필드 unique=True
                defaults={
                    "platform_name":         account_name,       # 플랫폼명
                    "representative_image":  rep_img_url,        # 대표이미지
                    "product_id":            origin_no,          # 상품ID
                    "option_id_stock":       opt_stk,            # 옵션ID재고
                    "expected_restock_date": None,               # 현재 API 데이터 없음
                    "order_product_name":    product_name,       # 주문상품명 = productName
                    "order_option_name_01":  opt_name1,          # 주문옵션명01
                    "order_option_name_02":  opt_name2,          # 주문옵션명02 (추가)
                    "option_code":           opt_code,           # 옵션코드 = sellerManagerCode
                    "original_price":        naver_sale_price,   # 정가 = salePrice
                    "sale_price":            naver_discounted_price,  # 할인가 = discountedPrice
                    "add_option_price":      add_opt_prc,        # 추가옵션가 = combo.price
                    # out_of_stock_at, updated_at → 필요 시 추가 로직
                }
            )
            updated_count += 1

    return JsonResponse({
        "message": f"{account_name} 상품/옵션 {updated_count}건 업데이트 완료",
        "count": updated_count,
    })

def naver_delete_all_data(request):
    """
    네이버 상품 데이터 전체 삭제
    """
    naverItem.objects.all().delete()
    messages.success(request, "네이버 상품 데이터 전체 삭제 완료.")
    return redirect('naver_product_list')


def naver_update_sales_view(request):
    logger.info("===== [naver_update_sales_view] CALLED =====")
    if request.method == 'POST':
        logger.info("POST로 들어옴!")
        start_str = request.POST.get('fetch_start_date')
        end_str   = request.POST.get('fetch_end_date')
        logger.info(f"[DEBUG] start_str={start_str}, end_str={end_str}")

        if start_str and end_str:
            try:
                from datetime import datetime
                import json

                start_dt = datetime.strptime(start_str, '%Y-%m-%d')
                end_dt   = datetime.strptime(end_str,   '%Y-%m-%d')

                # NAVER_ACCOUNTS의 모든 계정을 순회
                for account_info in NAVER_ACCOUNTS:
                    try:
                        logger.info(
                            "[DEBUG naver_update_sales_view] calling fetch_naver_sales for account [%s] with start=%s end=%s",
                            account_info['names'], start_dt, end_dt
                        )
                        result = fetch_naver_sales(account_info, start_dt, end_dt)

                        # (A) ★ 여기서 result를 로그로 찍어본다 (최대 1000자)
                        logger.info(
                            "[DEBUG naver_update_sales_view] fetch_naver_sales result for account [%s] =>\n%s",
                            account_info['names'],
                            json.dumps(result, ensure_ascii=False, indent=2)[:1000]
                        )

                        # (B) 기존 로직: result의 타입에 따라 orders 추출
                        if isinstance(result, dict):
                            orders = result.get("data", [])
                        elif isinstance(result, list):
                            orders = result
                        else:
                            orders = []

                        if orders:
                            logger.info(
                                "[DEBUG] calling update_naver_daily_sales with orders len=%d for account [%s]",
                                len(orders), account_info['names']
                            )
                            update_naver_daily_sales(orders, account_info)
                            messages.success(
                                request,
                                f"[{account_info['names']}] 네이버 매출 ({start_str} ~ {end_str}) 업데이트 완료!"
                            )
                        else:
                            logger.info(
                                "[DEBUG] no orders to save for account [%s], skip update_naver_daily_sales",
                                account_info['names']
                            )
                            messages.warning(
                                request,
                                f"[{account_info['names']}] 업데이트할 매출 없음."
                            )
                    except Exception as e:
                        logger.error(
                            "[ERROR] 네이버 매출 업데이트 중 예외 발생 for account [%s]",
                            account_info['names'], exc_info=True
                        )
                        messages.error(
                            request,
                            f"[{account_info['names']}] 네이버 매출 업데이트 오류: {str(e)}"
                        )
            except Exception as e:
                logger.error("[ERROR] 네이버 매출 업데이트 전반적 처리 중 예외 발생", exc_info=True)
                messages.error(request, f"네이버 매출 업데이트 오류: {str(e)}")
        else:
            messages.warning(request, "날짜를 선택해주세요!")

        return redirect('naver_sales_report')
    else:
        return redirect('naver_sales_report')
    
    
def naver_sales_report_view(request):
    logger.info("===== [naver_sales_report_view] START =====")

    # 1) GET 파라미터(start_date, end_date) 받아오기
    start_str = request.GET.get('start_date', '')
    end_str   = request.GET.get('end_date', '')

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date   = datetime.strptime(end_str,   "%Y-%m-%d").date()
        except ValueError:
            # 날짜 파싱 실패 시, 기본 14일 전 ~ 어제
            start_date = date.today() - timedelta(days=14)
            end_date   = date.today() - timedelta(days=1)
    else:
        # 파라미터 없으면 기본 14일 전 ~ 어제
        start_date = date.today() - timedelta(days=14)
        end_date   = date.today() - timedelta(days=1)

    # 2) 전체 날짜 리스트 (오름차순)
    day_count = (end_date - start_date).days + 1
    date_list = [start_date + timedelta(days=i) for i in range(day_count)]

    # (A) 테이블용 dates = 역정렬 (최근 날짜가 왼쪽)
    table_dates = [d.strftime('%Y-%m-%d') for d in date_list]
    table_dates.reverse()  # ex) ["2025-02-22","2025-02-21", ...]

    # (B) 차트용 dates = 오름차순 그대로
    chart_dates = [d.strftime('%Y-%m-%d') for d in date_list]

    # 3) DB 필터링
    #    date 필드는 "YYYY-MM-DD" 문자열이라고 가정
    daily_qs = NaverDailySales.objects.filter(
        date__gte=start_date.strftime('%Y-%m-%d'),
        date__lte=end_date.strftime('%Y-%m-%d')
    ).order_by('date')

    # ---------------------------
    # (I) 테이블용 grouped_data (역정렬)
    # ---------------------------
    from collections import defaultdict

    grouped_data_dict = {}
    # date_sums: 각 날짜별 합계 { "2025-02-21": { "qty":..., "revenue":... }, ... }
    date_sums = {td: {"qty":0, "revenue":0} for td in table_dates}

    grand_total_qty = 0
    grand_total_rev = 0

    for row in daily_qs:
        product_name = row.product_name or "(상품명없음)"
        option_name  = row.option_name or "(옵션없음)"

        # "net" 판매량, 매출 => (결제 - 환불)
        net_qty     = row.sales_qty - row.refunded_qty
        net_revenue = row.sales_revenue - row.refunded_revenue

        # 테이블에 날짜는 row.date ex) "2025-02-21"
        dstr = row.date

        # 1) grouped_data_dict[product_name] 초기화
        if product_name not in grouped_data_dict:
            grouped_data_dict[product_name] = {
                "product_name": product_name,
                "delivery_label": "판매자배송",  # 전부 판매자배송
                "product_sales": {},  # { date_str: { qty, revenue } }
                "options": {}
            }

        # 2) 옵션 레벨 초기화
        if option_name not in grouped_data_dict[product_name]["options"]:
            grouped_data_dict[product_name]["options"][option_name] = {
                "option_name": option_name,
                "delivery_label": "판매자배송",
                "option_sales": {}
            }

        # 3) 옵션 레벨 sales
        opt_sales = grouped_data_dict[product_name]["options"][option_name]["option_sales"]
        if dstr not in opt_sales:
            opt_sales[dstr] = {"qty":0, "revenue":0}
        opt_sales[dstr]["qty"]     += net_qty
        opt_sales[dstr]["revenue"] += net_revenue

        # 4) 상품 레벨 sales
        prod_sales = grouped_data_dict[product_name]["product_sales"]
        if dstr not in prod_sales:
            prod_sales[dstr] = {"qty":0, "revenue":0}
        prod_sales[dstr]["qty"]     += net_qty
        prod_sales[dstr]["revenue"] += net_revenue

    # 이제 date_sums, grand_total
    grouped_data = []
    for p_key, p_val in grouped_data_dict.items():
        # 상품별 합계
        product_total_qty = 0
        product_total_rev = 0

        # 상품 레벨 dict ex) p_val["product_sales"] = { "2025-02-21":{qty:..,rev:..}, ... }
        for d_str, val in p_val["product_sales"].items():
            product_total_qty += val["qty"]
            product_total_rev += val["revenue"]
            # date_sums
            if d_str in date_sums:
                date_sums[d_str]["qty"]     += val["qty"]
                date_sums[d_str]["revenue"] += val["revenue"]

        # 옵션 목록
        option_list = []
        for o_key, o_val in p_val["options"].items():
            # 옵션별 합계
            opt_total_qty = 0
            opt_total_rev = 0
            for d_str, oval in o_val["option_sales"].items():
                opt_total_qty += oval["qty"]
                opt_total_rev += oval["revenue"]

            option_list.append({
                "option_name": o_val["option_name"],
                "delivery_label": o_val["delivery_label"],
                "option_sales": o_val["option_sales"],
                "option_total": {
                    "qty": opt_total_qty,
                    "revenue": opt_total_rev
                }
            })

        grouped_data.append({
            "product_name": p_val["product_name"],
            "delivery_label": p_val["delivery_label"],
            "product_sales": p_val["product_sales"],
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
    # chart_dates= ["2025-02-10","2025-02-11",... ascending]
    # "total_t_amount" / "net_s_amount" / "total_t_items" / "net_s_items" 
    #   => 여기서는 단순히 sales_qty/revenue vs refunded, 
    #   => or "net" vs "total" 구분 가능. 
    #   아래 예: total= sales, net= (sales - refunded)
    #   but user said "네이버에는 순매출, 순판매상품수 이런건 없어" 
    #   We can adapt them to show "sales_revenue" & "net_revenue" etc.
    daily_dict = defaultdict(lambda: {
        "total_t_amount": 0,
        "net_s_amount": 0,
        "total_t_items": 0,
        "net_s_items": 0
    })

    for row in daily_qs:
        dstr = row.date
        # total => 결제, net => (결제-환불)
        total_amount = row.sales_revenue
        net_amount   = row.sales_revenue - row.refunded_revenue
        total_items  = row.sales_qty
        net_items    = row.sales_qty - row.refunded_qty

        daily_dict[dstr]["total_t_amount"] += total_amount
        daily_dict[dstr]["net_s_amount"]   += net_amount
        daily_dict[dstr]["total_t_items"]  += total_items
        daily_dict[dstr]["net_s_items"]    += net_items

    chart_data = {
        "labels": chart_dates,  # 오름차순
        "total_t_amount": [],
        "net_s_amount": [],
        "total_t_items": [],
        "net_s_items": []
    }

    # 차트용 fill
    for d in chart_dates:
        chart_data["total_t_amount"].append(daily_dict[d]["total_t_amount"])
        chart_data["net_s_amount"].append(daily_dict[d]["net_s_amount"])
        chart_data["total_t_items"].append(daily_dict[d]["total_t_items"])
        chart_data["net_s_items"].append(daily_dict[d]["net_s_items"])

    chart_data_json = json.dumps(chart_data)

    # 4) context
    context = {
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

    logger.info("===== [naver_sales_report_view] END =====")
    return render(request, "sales_management/naver_sales_report.html", context)



def update_naver_daily_sales(order_list, account_info):
    """
    :param order_list: 네이버 API로부터 받아온 주문 목록 
                      (각 item: { productOrder: {...}, order: {...} })
    :param account_info: { "names": ["스토어명1", ...], ... } 형태
    """
    from .models import NaverDailySales

    logger.info("===== [update_naver_daily_sales] START =====")

    # (A) account_info에서 스토어 이름 추출
    if "names" in account_info and account_info["names"]:
        store_name = account_info["names"][0]
    else:
        store_name = "(네이버스토어)"

    # (B) 결제(+)로 간주할 상태 목록
    PAID_STATUSES = ("PAYED", "DELIVERING", "DELIVERED", "PURCHASE_DECIDED", "DISPATCHED")

    for item in order_list:
        product_part = item.get("productOrder", {})
        order_part   = item.get("order", {})

        # 주요 필드
        order_id       = product_part.get("productOrderId", "")
        product_status = product_part.get("productOrderStatus", "")
        qty            = product_part.get("quantity", 0)
        total_pay_amt  = product_part.get("totalPaymentAmount", 0)

        # 수수료(paymentCommission + knowledgeShoppingSellingInterlockCommission)
        payment_commission   = product_part.get("paymentCommission", 0)
        knowledge_commission = product_part.get("knowledgeShoppingSellingInterlockCommission", 0)
        market_fee_val       = payment_commission + knowledge_commission

        # 상품명/옵션 및 옵션코드
        product_name = product_part.get("productName", "")
        product_opt  = product_part.get("productOption", "")
        option_code  = product_part.get("optionCode", "")

        # 새로운 필드: product_id 와 originalProductId
        product_id_val = product_part.get("productId", "")
        original_product_id_val = product_part.get("originalProductId", "")

        # 날짜(결제일)
        payment_date_str = order_part.get("paymentDate", "")
        date_str = payment_date_str[:10] if len(payment_date_str) >= 10 else ""

        logger.info(f"[update_naver_daily_sales] orderID={order_id}, status={product_status}, store={store_name}")

        # (C) DB에서 기존 레코드 조회
        try:
            sales_obj = NaverDailySales.objects.get(order_ID=order_id)
            logger.info(" -> existing record found.")
        except NaverDailySales.DoesNotExist:
            sales_obj = None

        # (D) 상태별 처리
        if product_status in PAID_STATUSES:
            # ------------------
            # 1) 결제(+) 처리
            # ------------------
            if not sales_obj:
                # 레코드가 없다면 새로 생성
                sales_obj = NaverDailySales(
                    date=date_str,
                    store=store_name,
                    order_ID=order_id,
                    product_name=product_name,
                    product_id=product_id_val,
                    originalProductId=original_product_id_val,
                    option_name=product_opt,
                    option_id=option_code,
                    optioncode=option_code,  # 추가 필드
                    sales_qty=qty,
                    sales_revenue=total_pay_amt,
                    refunded_qty=0,
                    refunded_revenue=0,
                    market_fee=market_fee_val,
                )
                logger.info(f" -> create new record: +qty={qty}, +rev={total_pay_amt}, +fee={market_fee_val}")
                sales_obj.save()
            else:
                # 기존 레코드가 있다면, product_id, originalProductId, optioncode 업데이트
                updated = False
                if sales_obj.product_id != product_id_val:
                    sales_obj.product_id = product_id_val
                    updated = True
                if sales_obj.originalProductId != original_product_id_val:
                    sales_obj.originalProductId = original_product_id_val
                    updated = True
                if sales_obj.optioncode != option_code:
                    sales_obj.optioncode = option_code
                    updated = True
                if updated:
                    logger.info(" -> existing record updated with new product_id, originalProductId and optioncode.")
                    sales_obj.save()
                else:
                    logger.info(" -> record already exists => skip update (+)")

        elif product_status == "RETURNED":
            # ------------------
            # 2) 반품 => 환불(-)
            # ------------------
            if not sales_obj:
                sales_obj = NaverDailySales(
                    date=date_str,
                    store=store_name,
                    order_ID=order_id,
                    product_name=product_name,
                    product_id=product_id_val,
                    originalProductId=original_product_id_val,
                    option_name=product_opt,
                    option_id=option_code,
                    optioncode=option_code,
                    sales_qty=0,
                    sales_revenue=0,
                    refunded_qty=qty,
                    refunded_revenue=total_pay_amt,
                    market_fee=market_fee_val,
                )
                logger.info(f" -> create new record for RETURNED: -qty={qty}, -rev={total_pay_amt}")
                sales_obj.save()
            else:
                sales_obj.refunded_qty     += qty
                sales_obj.refunded_revenue += total_pay_amt
                sales_obj.optioncode = option_code
                # 업데이트: product_id와 originalProductId 도 최신 값으로 반영
                if sales_obj.product_id != product_id_val:
                    sales_obj.product_id = product_id_val
                if sales_obj.originalProductId != original_product_id_val:
                    sales_obj.originalProductId = original_product_id_val
                logger.info(f" -> update record for RETURNED: -qty={qty}, -rev={total_pay_amt}")
                sales_obj.save()

        elif product_status == "CANCELED":
            # ------------------
            # 3) 취소 => 환불(-) (기존 레코드 있어야만)
            # ------------------
            if sales_obj:
                sales_obj.refunded_qty     += qty
                sales_obj.refunded_revenue += total_pay_amt
                sales_obj.optioncode = option_code  # 최신 옵션코드 반영
                # 업데이트: product_id와 originalProductId 도 최신 값으로 반영
                if sales_obj.product_id != product_id_val:
                    sales_obj.product_id = product_id_val
                if sales_obj.originalProductId != original_product_id_val:
                    sales_obj.originalProductId = original_product_id_val
                logger.info(f" -> update record for CANCELED: -qty={qty}, -rev={total_pay_amt}")
                sales_obj.save()
            else:
                logger.info(f" -> canceled but no record => skip")

        else:
            logger.info(f" -> status={product_status}, skip")

    logger.info("===== [update_naver_daily_sales] END =====")



def deleted_naver_sales(request):
    if request.method == 'POST':
        from django.contrib import messages
        # NaverDailySales 모델 임포트
        from .models import NaverDailySales

        # 모든 레코드 삭제
        NaverDailySales.objects.all().delete()

        messages.success(request, "네이버 매출 데이터 전체 삭제 완료!")
        return redirect('naver_sales_report')  # 혹은 원하는 페이지로

    # GET이면 그냥 리다이렉트
    return redirect('naver_sales_report')



#광고 시작



def naver_ad_report_view(request):
    import logging
    from datetime import date, timedelta, datetime
    from decimal import Decimal
    from collections import defaultdict, OrderedDict
    from django.db.models import Sum
    from django.shortcuts import render

    logger = logging.getLogger(__name__)
    logger.info("===== [naver_ad_report_view] START =====")

    # --- 1) 날짜 파라미터 처리 (GET)
    start_str = request.GET.get('start_date', '')
    end_str   = request.GET.get('end_date', '')
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date() if start_str else date.today() - timedelta(days=14)
        end_date   = datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else date.today() - timedelta(days=1)
    except ValueError:
        start_date = date.today() - timedelta(days=14)
        end_date   = date.today() - timedelta(days=1)

    # --- 2) 모델 임포트
    from .models import NaverAdReport, NaverAdShoppingProduct, NaverDailySales, naverItem

    # --- (A) naverItem에서 브랜드 매핑을 위한 채널ID 기반 맵 생성 (account_name)
    # 여기서는 channelProductID를 키로 사용
    brand_map = {}
    # 그리고 sku_to_channel 맵: skuID → channelProductID
    sku_to_channel = {}
    for item in naverItem.objects.all():
        sku = (item.skuID or "").strip()  # 기본적으로 skuID 사용
        channel = (item.channelProductID or "").strip()  # 브랜드 매칭용 채널ID
        brand = (item.account_name or "").strip() or "광고비"
        # 브랜드 매핑은 channelProductID 기준
        brand_map[channel] = brand
        # skuID에서 channelProductID로의 매핑 저장
        sku_to_channel[sku] = channel

    def get_label_from_sku(sku_str):
        """
        기본적으로 skuID를 전달받으면, sku_to_channel을 통해 channelProductID로 변환한 후
        brand_map에서 브랜드(account_name)를 반환한다.
        """
        sku_str = sku_str.strip()
        channel = sku_to_channel.get(sku_str, sku_str)
        result = brand_map.get(channel, "광고비")
        return result

    # --- (B) naverItem 맵 (상품명 매핑용) -> 기본적으로 skuID 사용
    naver_item_map = {}
    for it in naverItem.objects.all():
        if it.skuID:
            key = it.channelProductID.strip()
            naver_item_map[key] = it.itemName

    # --- (C) NaverAdShoppingProduct 조회 → sp_map 생성
    # 키는 ad_id(문자열)로 사용
    sp_map = {}
    for sp in NaverAdShoppingProduct.objects.all():
        key = sp.ad_id.strip() if sp.ad_id else ""
        sp_map[key] = {
            "product_name": sp.product_name.strip() if sp.product_name else "(상품미매칭)",
            "product_id_of_mall": (sp.product_id_of_mall or "").strip(),
        }

    # --- (D) NaverDailySales 조회 → sales_map_daily (일자별 판매 집계)
    sales_map_daily = defaultdict(lambda: {"qty": 0, "revenue": Decimal("0.00")})
    daily_sales_qs = NaverDailySales.objects.filter(
        date__gte=start_date.strftime("%Y-%m-%d"),
        date__lte=end_date.strftime("%Y-%m-%d")
    )
    for ds in daily_sales_qs:
        d_str = ds.date if isinstance(ds.date, str) else ds.date.strftime("%Y-%m-%d")
        final_qty = ds.sales_qty - ds.refunded_qty
        final_rev = ds.sales_revenue - ds.refunded_revenue
        sales_map_daily[d_str]["qty"] += final_qty
        sales_map_daily[d_str]["revenue"] += Decimal(final_rev)

    # --- (E) 광고 성과 집계 (ad_report_qs)
    ad_report_qs = NaverAdReport.objects.filter(date__range=[start_date, end_date])
    ad_data_map = defaultdict(lambda: {
        "impression": 0,
        "click": 0,
        "cost": Decimal("0.00"),
        "conversion_count": 0,
        "sales_by_conversion": Decimal("0.00"),
    })
    for row in ad_report_qs:
        key = row.ad_id.strip() if row.ad_id else ""
        if key in sp_map:
            product_name = sp_map[key]["product_name"]
        else:
            product_name = "(광고상품미매칭)"
        ad_data_map[key]["impression"] += row.impression or 0
        ad_data_map[key]["click"] += row.click or 0
        ad_data_map[key]["cost"] += row.cost or Decimal("0.00")
        ad_data_map[key]["conversion_count"] += row.conversion_count or 0
        ad_data_map[key]["sales_by_conversion"] += row.sales_by_conversion or Decimal("0.00")

    # --- (F) 미매칭 광고 목록
    unmatched_ads = []
    for key in ad_data_map.keys():
        if key not in sp_map:
            unmatched_ads.append({"ad_id": key})
            logger.warning("Unmatched ad_id: %s", key)
    unmatched_count = len(unmatched_ads)

    # --- (G) KPI 카드용 목록 생성 (card_items)
    card_items = []
    total_click = 0
    total_conv = 0
    for ad_id, ad_val in ad_data_map.items():
        cost_val = ad_val["cost"]
        rev_val  = ad_val["sales_by_conversion"]
        impression_val = ad_val["impression"]
        click_val = ad_val["click"]
        conv_val = ad_val["conversion_count"]

        spinfo = sp_map.get(ad_id, {})
        product_name = spinfo.get("product_name", "(광고상품미매칭)")
        pid_mall = spinfo.get("product_id_of_mall")

        # 판매 데이터 집계
        sales_qty = 0
        sales_rev = 0
        if pid_mall:
            for s_val in sales_map_daily.values():
                sales_qty += s_val["qty"]
                sales_rev += s_val["revenue"]

        roas_val = (rev_val / cost_val * 100) if cost_val > 0 else 0
        conv_rate = (conv_val / click_val * 100) if click_val > 0 else 0
        ctr_val = (click_val / impression_val * 100) if impression_val > 0 else 0
        ad_sales_rate = (conv_val / sales_qty * 100) if sales_qty > 0 else 0

        total_click += click_val
        total_conv += conv_val

        card_items.append({
            "product_name": product_name,
            "ad_revenue": rev_val,
            "ad_spend": cost_val,
            "roas": roas_val,
            "conversion_rate": conv_rate,
            "total_impressions": impression_val,
            "total_clicks": click_val,
            "ctr": ctr_val,
            "sales_qty": sales_qty,
            "sales_revenue": sales_rev,
            "ad_sales_rate": ad_sales_rate,
        })

    overall_conv_avg = (total_conv / total_click * 100) if total_click > 0 else 0
    roas_high = sorted([item for item in card_items if item["roas"] >= 600], key=lambda x: x["roas"], reverse=True)
    roas_low  = sorted([item for item in card_items if item["roas"] <= 200], key=lambda x: x["roas"])
    conv_low  = sorted([item for item in card_items if 0 < item["conversion_rate"] < overall_conv_avg], key=lambda x: x["conversion_rate"])

    # --- (H) 일자별 집계 (daily_sum_map)
    daily_sum_map = defaultdict(lambda: {
        "qty": 0,
        "ad_qty": 0,
        "revenue": Decimal("0.00"),
        "ad_revenue": Decimal("0.00"),
        "ad_spend": Decimal("0.00"),
        "profit": Decimal("0.00"),
        "click": 0,
    })
    for row in ad_report_qs:
        d_str = row.date.strftime("%Y-%m-%d")
        daily_sum_map[d_str]["ad_qty"] += (row.conversion_count or 0)
        daily_sum_map[d_str]["ad_revenue"] += (row.sales_by_conversion or Decimal("0.00"))
        daily_sum_map[d_str]["ad_spend"] += (row.cost or Decimal("0.00"))
        daily_sum_map[d_str]["profit"] += ((row.sales_by_conversion or Decimal("0.00")) - (row.cost or Decimal("0.00")))
        daily_sum_map[d_str]["click"] += (row.click or 0)
    for d_str, s_val in sales_map_daily.items():
        daily_sum_map[d_str]["qty"] += s_val["qty"]
        daily_sum_map[d_str]["revenue"] += s_val["revenue"]

    # --- (H-1) 세부 내역 (details) 구성: 일자별, 브랜드별 집계
    date_brand_map = defaultdict(lambda: defaultdict(lambda: {
        "qty": 0,
        "ad_qty": 0,
        "revenue": Decimal("0.00"),
        "ad_revenue": Decimal("0.00"),
        "ad_spend": Decimal("0.00"),
        "click": 0,
        "profit": Decimal("0.00"),
        "conversion_rate": 0,
        "roas": 0,
        "ad_sales_rate": 0,
        "kind": "",
    }))

    # 판매 세부 내역: NaverDailySales를 순회하며 브랜드 결정 시, 
    # 옵션(option_id)로 매핑한 결과가 "광고비"이면 store 필드로 대체
    for ds in daily_sales_qs:
        d_str = ds.date if isinstance(ds.date, str) else ds.date.strftime("%Y-%m-%d")
        sku_str = (ds.option_id or "").strip()
        if sku_str:
            brand_candidate = get_label_from_sku(sku_str)
            if brand_candidate == "광고비":
                # 옵션으로 매핑했는데 "광고비"로 나오면 내부의 store 필드를 사용
                brand = ds.store or "판매자배송"
            else:
                brand = brand_candidate
        else:
            brand = ds.store or "판매자배송"
        final_qty = ds.sales_qty - ds.refunded_qty
        final_rev = ds.sales_revenue - ds.refunded_revenue
        detail = date_brand_map[d_str][brand]
        detail["qty"] += final_qty
        detail["revenue"] += Decimal(final_rev)
        detail["kind"] = brand

    # 광고 세부 내역 (ad_id 단일키 기준)
    for ad in ad_report_qs:
        d_str = ad.date.strftime("%Y-%m-%d")
        key_ad = ad.ad_id.strip() if ad.ad_id else ""
        if key_ad in sp_map:
            sku_str = sp_map[key_ad]["product_id_of_mall"]  # 이 값은 기본적으로 skuID
            brand = get_label_from_sku(sku_str)              # skuID를 전달하면, get_label_from_sku에서 channelProductID로 변환하여 브랜드 반환
        else:
            brand = "광고비"
        detail = date_brand_map[d_str][brand]
        detail["ad_qty"] += ad.conversion_count or 0
        detail["ad_revenue"] += ad.sales_by_conversion or Decimal("0.00")
        detail["ad_spend"] += ad.cost or Decimal("0.00")
        detail["click"] += ad.click or 0

    # 파생 지표 계산
    for d_str, brands in date_brand_map.items():
        for brand, detail in brands.items():
            detail["profit"] = detail["revenue"] - detail["ad_spend"]
            detail["conversion_rate"] = (detail["ad_qty"] / detail["click"] * 100) if detail["click"] > 0 else 0
            detail["roas"] = (detail["ad_revenue"] / detail["ad_spend"] * 100) if detail["ad_spend"] > 0 else 0
            detail["ad_sales_rate"] = (detail["ad_qty"] / detail["qty"] * 100) if detail["qty"] > 0 else 0

    # --- (I) daily_reports 구성 (일자별 집계 + 세부 내역 추가)
    daily_reports = []
    for d_str in sorted(daily_sum_map.keys()):
        val = daily_sum_map[d_str]
        roas_val = (val["ad_revenue"] / val["ad_spend"] * 100) if val["ad_spend"] > 0 else 0
        conversion_rate_val = (val["ad_qty"] / val["click"] * 100) if val["click"] > 0 else 0
        ad_sales_rate_val = (val["ad_qty"] / val["qty"] * 100) if val["qty"] > 0 else 0
        detail_list = []
        if d_str in date_brand_map:
            for brand, detail in date_brand_map[d_str].items():
                detail_list.append(detail)
        daily_reports.append({
            "date_str": d_str,
            "qty": val["qty"],
            "ad_qty": val["ad_qty"],
            "conversion_rate": conversion_rate_val,
            "revenue": val["revenue"],
            "ad_revenue": val["ad_revenue"],
            "ad_spend": val["ad_spend"],
            "profit": val["profit"],
            "roas": roas_val,
            "ad_sales_rate": ad_sales_rate_val,
            "details": detail_list,
        })

    # --- (J) 전체 기간 소계 (period_summary)
    total_qty         = sum(x["qty"] for x in daily_reports)
    total_ad_qty      = sum(x["ad_qty"] for x in daily_reports)
    total_revenue     = sum(x["revenue"] for x in daily_reports)
    total_ad_revenue  = sum(x["ad_revenue"] for x in daily_reports)
    total_ad_spend    = sum(x["ad_spend"] for x in daily_reports)
    total_profit      = sum(x["profit"] for x in daily_reports)
    period_roas = (total_ad_revenue / total_ad_spend * 100) if total_ad_spend > 0 else 0
    period_ad_sales_rate = (total_ad_qty / total_qty * 100) if total_qty > 0 else 0
    total_clicks = 0
    total_conversions = 0
    for row in ad_report_qs:
        total_clicks += (row.click or 0)
        total_conversions += (row.conversion_count or 0)
    overall_conversion_rate = (total_conversions / total_clicks * 100) if total_clicks > 0 else 0

    period_summary = {
        "total_qty": total_qty,
        "total_ad_qty": total_ad_qty,
        "conversion_rate": overall_conversion_rate,
        "total_revenue": total_revenue,
        "ad_revenue": total_ad_revenue,
        "ad_spend": total_ad_spend,
        "profit": total_profit,
        "roas": period_roas,
        "ad_sales_rate": period_ad_sales_rate,
    }

    # --- (K) 전체 기간 브랜드별 상세 데이터 집계 (brand_details)
    brand_summary = defaultdict(lambda: {
        "qty": 0,
        "ad_qty": 0,
        "net_sales_amount": Decimal("0.00"),
        "commission": Decimal("0.00"),
        "ad_spend": Decimal("0.00"),
        "purchase_cost": Decimal("0.00"),
        "etc_cost": Decimal("0.00"),
        "profit": Decimal("0.00"),
        "ad_revenue": Decimal("0.00"),   # 추가: 광고 전환 매출 누적
        "click": 0,                      # 추가: 클릭 수 누적
    })

    for day in daily_reports:
        for det in day.get("details", []):
            brand = det.get("kind", "판매자배송")
            brand_summary[brand]["qty"] += det.get("qty", 0)
            brand_summary[brand]["ad_qty"] += det.get("ad_qty", 0)
            brand_summary[brand]["net_sales_amount"] += det.get("revenue", Decimal("0.00"))
            brand_summary[brand]["commission"] += det.get("commission", Decimal("0.00"))
            brand_summary[brand]["ad_spend"] += det.get("ad_spend", Decimal("0.00"))
            brand_summary[brand]["purchase_cost"] += det.get("purchase_cost", Decimal("0.00"))
            brand_summary[brand]["etc_cost"] += det.get("etc_cost", Decimal("0.00"))
            brand_summary[brand]["profit"] += det.get("profit", Decimal("0.00"))
            # 추가: 광고 매출 및 클릭 수 누적
            brand_summary[brand]["ad_revenue"] += det.get("ad_revenue", Decimal("0.00"))
            brand_summary[brand]["click"] += det.get("click", 0)

    brand_details = {}
    for b, data in brand_summary.items():
        # 계산: 전환율 (클릭 대비 광고 전환수), ROAS (광고 전환 매출 대비 광고 집행비)
        conversion_rate = (data["ad_qty"] / data["click"] * 100) if data["click"] > 0 else 0
        roas = (data["ad_revenue"] / data["ad_spend"] * 100) if data["ad_spend"] > 0 else 0
        m_rate = (data["profit"] / data["net_sales_amount"] * 100) if data["net_sales_amount"] > 0 else 0
        brand_details[b] = {
            "qty": data["qty"],
            "ad_qty": data["ad_qty"],
            "net_sales_amount": data["net_sales_amount"],
            "commission": data["commission"],
            "ad_spend": data["ad_spend"],
            "purchase_cost": data["purchase_cost"],
            "etc_cost": data["etc_cost"],
            "profit": data["profit"],
            "margin_rate": m_rate,
            "conversion_rate": conversion_rate,  # 추가
            "ad_revenue": data["ad_revenue"],      # 추가
            "roas": roas,                          # 추가
        }
    period_summary["brand_details"] = brand_details

    # --- (L) 모달용: 일자별 상품별 상세 데이터 생성 (overall modal)
    day_p_o_map = defaultdict(lambda: {
        "sold_qty": 0, 
        "sales_amt": Decimal("0.00"), 
        "ad_qty": 0, 
        "ad_spend": Decimal("0.00"), 
        "ad_revenue": Decimal("0.00"),
        "click": 0
    })
    for ds in daily_sales_qs:
        day_str = ds.date if isinstance(ds.date, str) else ds.date.strftime("%Y-%m-%d")
        pid = ds.product_id.strip() if ds.product_id else ""
        final_qty = ds.sales_qty - ds.refunded_qty
        final_rev = ds.sales_revenue - ds.refunded_revenue
        key = (day_str, pid)
        day_p_o_map[key]["sold_qty"] += final_qty
        day_p_o_map[key]["sales_amt"] += Decimal(final_rev)

    for ad in ad_report_qs:
        day_str = ad.date.strftime("%Y-%m-%d")
        key_ad = ad.ad_id.strip() if ad.ad_id else ""
        sp_info = sp_map.get(key_ad)
        if not sp_info:
            continue
        pid = sp_info.get("product_id_of_mall")
        if not pid:
            continue
        pid = pid.strip()
        key = (day_str, pid)
        day_p_o_map[key]["ad_qty"] += ad.conversion_count or 0
        day_p_o_map[key]["ad_spend"] += ad.cost or Decimal("0.00")
        day_p_o_map[key]["ad_revenue"] += ad.sales_by_conversion or Decimal("0.00")
        day_p_o_map[key]["click"] += ad.click or 0

    # --- (M) Build day_products_map: { date : { product_id : { ... } } }
    day_products_map = defaultdict(lambda: OrderedDict())
    for (day_str, pid), vals in day_p_o_map.items():
        sold_qty = vals["sold_qty"]
        sales_amt = vals["sales_amt"]
        ad_qty = vals["ad_qty"]
        ad_spend = vals["ad_spend"]
        ad_rev = vals["ad_revenue"]
        total_click = vals["click"]

        profit_val = ad_rev - ad_spend
        roas_val = (ad_rev / ad_spend * 100) if ad_spend else 0
        ad_sales_rate_val = (ad_qty / sold_qty * 100) if sold_qty else 0
        conversion_rate_val = (ad_qty / total_click * 100) if total_click else 0

        product_name = naver_item_map.get(pid, "(상품명없음)")

        if pid not in day_products_map[day_str]:
            day_products_map[day_str][pid] = {
                "product_id": pid,
                "product_name": product_name,
                "sold_qty": 0,
                "ad_qty": 0,
                "sales_amt": Decimal("0.00"),
                "ad_spend": Decimal("0.00"),
                "ad_revenue": Decimal("0.00"),
                "profit": Decimal("0.00"),
                "roas": 0,
                "ad_sales_rate": 0,
                "click": 0,
                "conversion_rate": 0,
            }

        rec = day_products_map[day_str][pid]
        rec["sold_qty"] += sold_qty
        rec["sales_amt"] += sales_amt
        rec["ad_qty"] += ad_qty
        rec["ad_spend"] += ad_spend
        rec["ad_revenue"] += ad_rev
        rec["click"] += total_click

        rec["profit"] = rec["ad_revenue"] - rec["ad_spend"]
        rec["roas"] = (rec["ad_revenue"] / rec["ad_spend"] * 100) if rec["ad_spend"] else 0
        rec["ad_sales_rate"] = (rec["ad_qty"] / rec["sold_qty"] * 100) if rec["sold_qty"] else 0
        rec["conversion_rate"] = (rec["ad_qty"] / rec["click"] * 100) if rec["click"] else 0

    # 필터링: 모든 수치가 0인 항목 삭제
    for day in list(day_products_map.keys()):
        for pid in list(day_products_map[day].keys()):
            rec = day_products_map[day][pid]
            if (
                rec["sold_qty"] == 0 and
                rec["ad_qty"] == 0 and
                rec["sales_amt"] == Decimal("0.00") and
                rec["ad_spend"] == Decimal("0.00") and
                rec["ad_revenue"] == Decimal("0.00") and
                rec["profit"] == Decimal("0.00")
            ):
                del day_products_map[day][pid]
        if not day_products_map[day]:
            del day_products_map[day]

    import json
    def convert_keys(obj):
        if isinstance(obj, dict):
            return {str(k): convert_keys(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_keys(item) for item in obj]
        elif isinstance(obj, Decimal):
            return float(obj)
        else:
            return obj

    day_products_map_json = json.dumps(convert_keys(day_products_map), ensure_ascii=False)

    # --- (N) 모달용: 전체 기간 상품별 상세 데이터 생성 (overall modal)
    overall_products_map = defaultdict(lambda: {
        "sold_qty": 0,
        "sales_amt": Decimal("0.00"),
        "ad_qty": 0,
        "ad_spend": Decimal("0.00"),
        "ad_revenue": Decimal("0.00")
    })

    for ds in daily_sales_qs:
        pid = (ds.product_id or "").strip()
        final_qty = ds.sales_qty - ds.refunded_qty
        final_rev = ds.sales_revenue - ds.refunded_revenue
        overall_products_map[pid]["sold_qty"] += final_qty
        overall_products_map[pid]["sales_amt"] += Decimal(final_rev)

    for ad in ad_report_qs:
        key_ad = ad.ad_id.strip() if ad.ad_id else ""
        sp_info = sp_map.get(key_ad)
        if not sp_info:
            continue
        pid = (sp_info.get("product_id_of_mall") or "").strip()
        overall_products_map[pid]["ad_qty"] += (ad.conversion_count or 0)
        overall_products_map[pid]["ad_spend"] += (ad.cost or Decimal("0.00"))
        overall_products_map[pid]["ad_revenue"] += (ad.sales_by_conversion or Decimal("0.00"))

    overall_details = []
    for pid, data in overall_products_map.items():
        if (data["sold_qty"] == 0 and 
            data["sales_amt"] == Decimal("0.00") and 
            data["ad_qty"] == 0 and 
            data["ad_spend"] == Decimal("0.00") and 
            data["ad_revenue"] == Decimal("0.00")):
            continue
        profit_val = data["ad_revenue"] - data["ad_spend"]
        roas_val = (data["ad_revenue"] / data["ad_spend"] * 100) if data["ad_spend"] else 0
        ad_sales_rate = (data["ad_qty"] / data["sold_qty"] * 100) if data["sold_qty"] else 0
        product_name = naver_item_map.get(pid, f"상품({pid})")
        overall_details.append({
            "product_id": pid,
            "product_name": product_name,
            "sold_qty": data["sold_qty"],
            "sales_amt": data["sales_amt"],
            "ad_qty": data["ad_qty"],
            "ad_spend": data["ad_spend"],
            "ad_revenue": data["ad_revenue"],
            "profit": profit_val,
            "roas": roas_val,
            "ad_sales_rate": ad_sales_rate,
        })

    overall_products_map_json = json.dumps(convert_keys(overall_details), ensure_ascii=False)
    
    context = {
        "start_date": start_date,
        "end_date": end_date,
        "daily_reports": daily_reports,
        "period_summary": period_summary,
        "roas_high": roas_high,
        "roas_low": roas_low,
        "conv_low": conv_low,
        "unmatched_count": unmatched_count,
        "unmatched_list": unmatched_ads,
        "day_products_map_json": day_products_map_json,
        "overall_products_map_json": overall_products_map_json,  # 전체기간 모달용 데이터
    }
    return render(request, "sales_management/naver_ad_report.html", context)



from decouple import config






from .api_clients import (
    NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID,
    create_master_report, get_master_report,
    create_stat_report, get_stat_report,
    get_header,delete_all_master_reports
)
import time

def download_report(download_url: str, file_name: str):
    """
    download_url: 응답의 downloadUrl (쿼리 파라미터 포함)
    file_name: "YYYYMMDD_item이름.csv"
    
    /report-download URI로 서명 & 헤더 생성 -> download_url로 GET 요청
    파일을 sales_management/download/[file_name] 경로에 저장
    """
    if not download_url:
        logger.error("Download URL is empty.")
        return None

    current_dir = os.path.dirname(os.path.abspath(__file__))
    download_folder = os.path.join(current_dir, "download")
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)
    file_path = os.path.join(download_folder, file_name)

    # 서명 생성 시 URI: "/report-download"
    uri = "/report-download"
    method = "GET"
    headers = get_header(method, uri, NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID)
    
    try:
        response = requests.get(download_url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"[download_report] Saved file to {file_path}")
        return file_path
    except requests.RequestException as e:
        logger.error(f"Failed to download report: {e}")
        return None

def naver_update_ads_report(request):
    """
    1) Stat Report: AD_DETAIL, AD_CONVERSION_DETAIL 생성 → 조회 → CSV 다운로드 (선택한 날짜 범위 내 각 날짜별)
    2) 다운로드된 CSV 파일들을 파싱하여 NaverAdReport 테이블에 저장
    """
    logger.debug("naver_update_ads_report 함수 시작")
    
    if request.method == 'POST':
        logger.debug("POST 요청 수신됨")
        if not all([NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID]):
            messages.error(request, "네이버 광고 API 설정이 누락되었습니다.")
            logger.debug("네이버 광고 API 설정 누락")
            return redirect('naver_ad_report')
        
        # POST로 전달된 날짜 (캘린더에서)
        raw_start = request.POST.get('fetch_start_date', '')
        raw_end = request.POST.get('fetch_end_date', '')
        logger.debug(f"raw_start: {raw_start}, raw_end: {raw_end}")
        
        # 기본값: 오늘 날짜
        try:
            start_date = datetime.strptime(raw_start, "%Y-%m-%d").date() if raw_start else datetime.now().date()
            end_date = datetime.strptime(raw_end, "%Y-%m-%d").date() if raw_end else datetime.now().date()
            logger.debug(f"start_date: {start_date}, end_date: {end_date}")
        except ValueError as ve:
            logger.debug(f"날짜 파싱 에러 발생: {ve}")
            start_date = datetime.now().date()
            end_date = datetime.now().date()
        
        # Stat Report는 날짜별로 생성하므로, 날짜 범위를 순회
        current_date = start_date
        while current_date <= end_date:
            stat_dt_str = current_date.strftime("%Y%m%d")
            logger.debug(f"처리 중 날짜: {stat_dt_str}")
            for report_tp in ["AD_DETAIL", "AD_CONVERSION_DETAIL"]:
                logger.debug(f"{report_tp} 작업 시작 for {stat_dt_str}")
                stat_res = create_stat_report(report_tp, stat_dt_str)
                if not stat_res or "reportJobId" not in stat_res:
                    messages.warning(request, f"[Stat] {report_tp} 생성 실패 for {stat_dt_str}")
                    logger.warning(f"{report_tp} 생성 실패 for {stat_dt_str} - stat_res: {stat_res}")
                    continue
                report_job_id = stat_res["reportJobId"]
                logger.debug(f"{report_tp} 생성 성공 for {stat_dt_str}, report_job_id: {report_job_id}")
                time.sleep(5)  # 5초 대기
                detail_stat = get_stat_report(report_job_id)
                if not detail_stat:
                    messages.warning(request, f"[Stat] {report_tp}, id={report_job_id} 조회 실패 for {stat_dt_str}")
                    logger.warning(f"{report_tp} 조회 실패 for {stat_dt_str} with report_job_id: {report_job_id}")
                    continue
                download_url = detail_stat.get("downloadUrl")
                file_name = f"{stat_dt_str}_{report_tp}.csv"
                if download_url:
                    saved_file = download_report(download_url, file_name)
                    if saved_file:
                        messages.success(request, f"[Stat] {report_tp} 다운로드 성공 for {stat_dt_str} → {saved_file}")
                        logger.debug(f"{report_tp} 다운로드 성공 for {stat_dt_str}, saved_file: {saved_file}")
                    else:
                        messages.error(request, f"[Stat] {report_tp} 다운로드 실패 for {stat_dt_str}")
                        logger.error(f"{report_tp} 다운로드 실패 for {stat_dt_str} - saved_file: {saved_file}")
                else:
                    messages.info(request, f"[Stat] {report_tp} downloadUrl 미존재 for {stat_dt_str}")
                    logger.info(f"{report_tp} downloadUrl 미존재 for {stat_dt_str}")
            current_date += timedelta(days=1)
        
        logger.debug("CSV 파일 파싱 및 DB 업데이트 시작")
        # CSV 파일들을 파싱하여 NaverAdReport 업데이트
        save_naver_ads_report()
        logger.debug("CSV 파일 파싱 및 DB 업데이트 완료")
        
        messages.success(request, "선택한 날짜 범위의 Stat Report 다운로드 및 DB 업데이트 완료")
        logger.debug("최종 성공 메시지 전송, naver_ad_report 페이지로 리다이렉트")
        return redirect('naver_ad_report')
    else:
        logger.debug("POST 요청이 아님, naver_ad_report 페이지로 리다이렉트")
        return redirect('naver_ad_report')    

def naver_update_ads_shopping_product(request):
    """
    1) Master Report: ShoppingProduct 생성 → 조회 → CSV 다운로드  
    2) 다운로드된 ShoppingProduct.csv → NaverAdShoppingProduct 테이블에 저장
    만약 생성 시 "exceeded limit" 오류가 발생하면, 전체 Master Report를 삭제하고 재시도합니다.
    """
    if request.method == 'POST':
        # (A) 네이버 광고 API 설정 체크
        if not all([NAVER_AD_ACCESS, NAVER_AD_SECRET, CUSTOMER_ID]):
            messages.error(request, "네이버 광고 API 설정이 누락되었습니다.")
            return redirect('naver_ad_report')
        
        # (B) 기간 파라미터 (fromTime)
        raw_start = request.POST.get('fetch_start_date', '')
        try:
            from_time = f"{raw_start}T00:00:00Z" if raw_start else datetime.now().strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            from_time = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
        
        today_str = datetime.now().strftime("%Y%m%d")
        master_item = "ShoppingProduct"
        
        # (C) Master Report 생성 (item="ShoppingProduct")
        master_res = create_master_report(master_item, from_time)
        # 만약 생성 실패하고, 오류 메시지에 "exceeded limit"이 포함되어 있다면 삭제 후 재시도
        if not master_res or "id" not in master_res:
            # 여기서는 master_res가 None일 경우도 포함
            logger.warning(f"[Master] {master_item} 생성 실패. 시도된 from_time: {from_time}")
            # (에러 메시지에 exceeded limit이 언급되었는지 여부를 판단할 수 있으면 조건 추가 가능)
            delete_all_master_reports()
            time.sleep(3)
            master_res = create_master_report(master_item, from_time)
            if not master_res or "id" not in master_res:
                messages.warning(request, f"[Master] {master_item} 생성 재시도 실패")
            else:
                messages.info(request, f"[Master] {master_item} 생성 재시도 성공")
        
        if master_res and "id" in master_res:
            report_id = master_res["id"]
            time.sleep(5)  # 5초 대기
            detail_res = get_master_report(report_id)
            if not detail_res:
                messages.warning(request, f"[Master] {master_item}, id={report_id} 조회 실패")
            else:
                download_url = detail_res.get("downloadUrl")
                file_name = f"{today_str}_{master_item}.csv"
                if download_url:
                    saved_file = download_report(download_url, file_name)
                    if saved_file:
                        messages.success(request, f"[Master] {master_item} 다운로드 성공 -> {saved_file}")
                    else:
                        messages.error(request, f"[Master] {master_item} 다운로드 실패")
                else:
                    messages.info(request, f"[Master] {master_item} downloadUrl 미존재")
        # (D) CSV 파싱 → NaverAdShoppingProduct 저장
        save_naver_shopping_product()
        
        messages.success(request, "쇼핑상품 데이터 업데이트 완료")
        return redirect('naver_ad_report')
    else:
        return redirect('naver_ad_report')
    

import csv
from .models import NaverAdReport,NaverAdShoppingProduct
from django.db import transaction

def find_all_files(folder_path, item_name):
    """
    폴더 내에서 'item_name'이 포함되고 확장자가 .csv인 모든 파일의 전체 경로 리스트를 반환합니다.
    """
    target_files = []
    for fname in os.listdir(folder_path):
        if item_name in fname and fname.endswith(".csv"):
            full_path = os.path.join(folder_path, fname)
            target_files.append(full_path)
    return target_files

def delete_processed_files(folder_path, item_name):
    """
    folder_path 내에서 'item_name'이 포함된 모든 CSV 파일을 삭제합니다.
    """
    files = find_all_files(folder_path, item_name)
    for file_path in files:
        try:
            os.remove(file_path)
            print(f"Deleted file: {file_path}")
        except Exception as e:
            print(f"Failed to delete file {file_path}: {e}")

def parse_ad_detail_all(download_dir):
    """
    AD_DETAIL.csv 파일들을 모두 읽어서,
    dict[(date, ad_group_id, ad_id)] = {impression, click, cost}  
    각 행의 수치를 합산하여 반환합니다.
    """
    detail_dict = {}
    files = find_all_files(download_dir, "AD_DETAIL")
    for file_path in files:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter='\t')
            for row in reader:
                if len(row) < 16:
                    logger.warning(f"Skipping row in AD_DETAIL due to insufficient columns: {row}")
                    continue
                dt_str = row[0]
                ad_group_id = row[3]
                ad_id = row[5]
                impression = parse_int_safely(row[11])
                click = parse_int_safely(row[12])
                cost = parse_decimal_safely(row[13])
                try:
                    date_obj = datetime.strptime(dt_str, "%Y%m%d").date()
                except Exception as e:
                    logger.warning(f"Skipping row due to invalid date: {row} - {e}")
                    continue
                key = (date_obj, ad_group_id, ad_id)
                if key not in detail_dict:
                    detail_dict[key] = {"impression": 0, "click": 0, "cost": Decimal("0.00")}
                detail_dict[key]["impression"] += impression
                detail_dict[key]["click"] += click
                detail_dict[key]["cost"] += cost
    return detail_dict

def parse_ad_conversion_all(download_dir):
    """
    AD_CONVERSION_DETAIL.csv 파일들을 모두 읽어서,
    dict[(date, ad_group_id, ad_id)] = {conversion_count, sales_by_conversion}  
    각 행의 수치를 합산하여 반환합니다.
    """
    conv_dict = {}
    files = find_all_files(download_dir, "AD_CONVERSION_DETAIL")
    for file_path in files:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter='\t')
            for row in reader:
                if len(row) < 15:
                    logger.warning(f"Skipping row in AD_CONVERSION_DETAIL due to insufficient columns: {row}")
                    continue
                dt_str = row[0]
                ad_group_id = row[3]
                ad_id = row[5]
                conv_count = parse_int_safely(row[13])
                sales_conv = parse_decimal_safely(row[14])
                try:
                    date_obj = datetime.strptime(dt_str, "%Y%m%d").date()
                except Exception as e:
                    logger.warning(f"Skipping row in AD_CONVERSION_DETAIL due to date parsing error: {row} - {e}")
                    continue
                key = (date_obj, ad_group_id, ad_id)
                if key not in conv_dict:
                    conv_dict[key] = {"conversion_count": 0, "sales_by_conversion": Decimal("0.00")}
                conv_dict[key]["conversion_count"] += conv_count
                conv_dict[key]["sales_by_conversion"] += sales_conv
    return conv_dict

def save_naver_ads_report():
    """
    1) AD_DETAIL.csv 파일들 → detail_dict: dict[(date, ad_group_id, ad_id)] = {impression, click, cost}
    2) AD_CONVERSION_DETAIL.csv 파일들 → conv_dict: dict[(date, ad_group_id, ad_id)] = {conversion_count, sales_by_conversion}
    두 데이터를 합산한 후, NaverAdReport 모델에 업데이트합니다.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    download_dir = os.path.join(base_dir, "download")

    detail_dict = parse_ad_detail_all(download_dir)
    conv_dict = parse_ad_conversion_all(download_dir)

    with transaction.atomic():
        for key, detail_val in detail_dict.items():
            (d_date, d_ag, d_ad) = key
            conv_val = conv_dict.get(key, {})
            impression = detail_val.get("impression", 0)
            click = detail_val.get("click", 0)
            cost = detail_val.get("cost", Decimal("0.00"))
            conversion_count = conv_val.get("conversion_count", 0)
            sales_by_conv = conv_val.get("sales_by_conversion", Decimal("0.00"))
            if impression > 0:
                ctr = (Decimal(click) / Decimal(impression)) * 100
            else:
                ctr = None
            roas = (cost / Decimal(conversion_count)) if conversion_count > 0 else None
            computed_ad_cost = int(cost * Decimal("1.1"))

            NaverAdReport.objects.update_or_create(
                date=d_date,
                ad_group_id=d_ag,
                ad_id=d_ad,
                defaults={
                    "impression": impression,
                    "click": click,
                    "cost": computed_ad_cost,  # 여기서 이미 1.1배 적용
                    "conversion_count": conversion_count,
                    "sales_by_conversion": sales_by_conv,
                    "ctr": ctr,
                    "roas": roas,
                }
            )
    logger.info("=== [save_naver_ads_report] NaverAdReport updated ===")
    
    delete_processed_files(download_dir, "AD_DETAIL")
    delete_processed_files(download_dir, "AD_CONVERSION_DETAIL")
    delete_processed_files(download_dir, "ShoppingProduct")

def save_naver_shopping_product():
    """
    ShoppingProduct.csv 파싱 → NaverAdShoppingProduct 모델에 Insert/Update
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    download_dir = os.path.join(base_dir, "download")
    
    # find_all_files()는 파일 경로 리스트를 반환하므로, 최신 파일을 선택합니다.
    csv_files = find_all_files(download_dir, "ShoppingProduct")
    if not csv_files:
        logger.info("ShoppingProduct CSV not found, skipping.")
        return

    csv_path = sorted(csv_files, key=lambda p: os.path.getmtime(p), reverse=True)[0]

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter='\t')
        for row in reader:
            if len(row) < 16:
                logger.warning(f"Skipping row in ShoppingProduct due to insufficient columns: {row}")
                continue
            try:
                ad_group_id = row[1]
                ad_id = row[2]
                product_id = row[12]
                product_id_of_mall = row[13]
                product_name = row[14]
                product_image_url = row[15]
            except IndexError as e:
                logger.error(f"IndexError in ShoppingProduct row: {row} - {e}")
                continue
            
            # DB 저장 (update_or_create)
            NaverAdShoppingProduct.objects.update_or_create(
                ad_group_id=ad_group_id,
                ad_id=ad_id,
                defaults={
                    "product_id": product_id,
                    "product_id_of_mall": product_id_of_mall,
                    "product_name": product_name,
                    "product_image_url": product_image_url
                }
            )
    
    logger.info("=== [save_naver_shopping_product] NaverAdShoppingProduct updated ===")




# def find_latest_file(folder_path, item_name):
#     """
#     폴더 안에서 '{item_name}.csv' 또는 'YYYYMMDD_{item_name}.csv' 형태 파일을 찾는 헬퍼 함수.
#     여러 파일이 있을 경우, 가장 최근 파일을 반환.
#     """
#     target_files = []
#     for fname in os.listdir(folder_path):
#         if item_name in fname and fname.endswith(".csv"):
#             full_path = os.path.join(folder_path, fname)
#             target_files.append(full_path)
#     if not target_files:
#         return None
#     target_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
#     return target_files[0]


# 헬퍼: parse_decimal_safely, parse_int_safely
def parse_decimal_safely(num_str):
    if not num_str:
        return Decimal("0.00")
    try:
        return Decimal(num_str)
    except:
        return Decimal("0.00")

def parse_int_safely(num_str):
    if not num_str:
        return 0
    try:
        return int(float(num_str))
    except:
        return 0
    



def naver_profit_report_view(request):
    """
    (쿠팡→네이버 치환 버전) + 상품별 모달용 데이터 생성.
    날짜 & 브랜드 기준으로 판매/광고를 합산 → 순수익 계산.
    """
    from datetime import date, datetime, timedelta
    from collections import defaultdict, OrderedDict
    import json
    from django.db.models import Sum
    from django.shortcuts import render
    from decimal import Decimal
    import logging

    logger = logging.getLogger(__name__)

    from sales_management.models import (
        NaverDailySales,
        NaverAdReport,
        NaverPurchaseCost,
        naverItem,
        NaverAdShoppingProduct
    )

    # (1) 날짜 범위 파싱
    start_str = request.GET.get('start_date', '')
    end_str   = request.GET.get('end_date', '')
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

    # ---------------------------------------------------------
    # (A) naverItem 매핑: 기본 SKU 매핑은 skuID, 브랜드 매칭은 channelProductID 사용
    # 1) sku_to_channel: skuID → channelProductID
    # 2) channel_brand_map: channelProductID → account_name (브랜드)
    sku_to_channel = {}
    channel_brand_map = {}
    for item in naverItem.objects.all():
        sku = (item.skuID or "").strip()
        channel = (item.channelProductID or "").strip()
        brand = (item.account_name or "").strip() or "광고비"
        sku_to_channel[sku] = channel
        channel_brand_map[channel] = brand

    def get_label_from_sku(sku_str):
        """
        기본적으로 skuID를 전달받으면, 먼저 전달된 값이 이미 channelProductID(채널 기준)라면
        channel_brand_map에서 바로 브랜드를 반환.
        그렇지 않으면, sku_to_channel을 통해 채널ProductID로 변환 후
        channel_brand_map에서 브랜드(account_name)를 반환.
        """
        sku_str = sku_str.strip()
        # 만약 sku_str이 channel_brand_map의 키로 이미 존재한다면 (즉, channelProductID라면)
        if sku_str in channel_brand_map:
            result = channel_brand_map[sku_str]
            return result
        channel = sku_to_channel.get(sku_str, sku_str)
        result = channel_brand_map.get(channel, "광고비")
        return result

    # ---------------------------------------------------------
    # (B) naverItem 맵 (상품명 매핑용) → channelProductID 기준
    naver_item_map = {}
    for it in naverItem.objects.all():
        if it.channelProductID:
            key = it.channelProductID.strip()
            naver_item_map[key] = it.itemName

    # ---------------------------------------------------------
    # (C) NaverAdShoppingProduct 조회 → sp_map 생성
    sp_map = {}
    for sp in NaverAdShoppingProduct.objects.all():
        key = (sp.ad_group_id, sp.ad_id)
        sp_map[key] = {
            "product_name": sp.product_name.strip() if sp.product_name else "(광고상품미매칭)",
            "product_id_of_mall": (sp.product_id_of_mall or "").strip(),  # SKU 값
        }

    # ---------------------------------------------------------
    # (D) NaverDailySales 조회
    daily_sales_qs = NaverDailySales.objects.filter(
        date__gte=start_d.strftime("%Y-%m-%d"),
        date__lte=end_d.strftime("%Y-%m-%d")
    )

    daily_map = defaultdict(lambda: {
        "sold_items": 0,
        "net_sales": 0,
        "purchase_cost": 0,
        "etc_cost": 0,
    })

    def get_brand_from_sales(ds):
        sku = (ds.option_id or "").strip()
        if sku:
            brand_candidate = get_label_from_sku(sku)
            # 만약 옵션으로 매핑한 브랜드가 "광고비"라면 store 필드 값을 사용
            if brand_candidate == "광고비":
                return ds.store or "판매자배송"
            else:
                return brand_candidate
        else:
            return ds.store or "판매자배송"

    # 매핑되지 않는 항목 디버깅: 옵션이 있는데 get_label_from_sku 결과가 "광고비"인 경우
    for ds in daily_sales_qs:
        d_str = ds.date  # 날짜 그대로 사용
        sold_qty = ds.sales_qty - ds.refunded_qty
        net_s = ds.sales_revenue - ds.refunded_revenue

        sku = (ds.option_id or "").strip()
        brand_label = get_brand_from_sales(ds)
        if sku and brand_label == "광고비":
            channel = sku_to_channel.get(sku, "N/A")
            mapped_account = channel_brand_map.get(channel, "N/A")
            itemName = naver_item_map.get(channel, "N/A")
                         

        try:
            cost_obj = NaverPurchaseCost.objects.get(sku_id=sku)
            unit_price = cost_obj.purchasing_price
        except NaverPurchaseCost.DoesNotExist:
            unit_price = 0
        partial_cost = unit_price * sold_qty

        daily_map[(d_str, brand_label)]["sold_items"] += sold_qty
        daily_map[(d_str, brand_label)]["net_sales"] += net_s
        daily_map[(d_str, brand_label)]["purchase_cost"] += partial_cost
        daily_map[(d_str, brand_label)]["etc_cost"] += 0

    # ---------------------------------------------------------
    # (E) 광고 데이터 조회
    ad_report_qs = NaverAdReport.objects.filter(
        date__range=[start_d, end_d]
    )

    ad_map = defaultdict(lambda: {
        "ad_sold": 0,
        "ad_spend": Decimal("0.00"),
        "ad_rev": Decimal("0.00"),
    })

    for ad in ad_report_qs:
        d_str = ad.date.strftime("%Y-%m-%d") if ad.date else ""
        key_sp = (ad.ad_group_id, ad.ad_id)
        sp_info = sp_map.get(key_sp)
        if not sp_info:
            continue

        sku_for_brand = sp_info["product_id_of_mall"]  # SKU 값
        brand_label = get_label_from_sku(sku_for_brand)
        
        ad_map[(d_str, brand_label)]["ad_sold"] += (ad.conversion_count or 0)
        ad_map[(d_str, brand_label)]["ad_spend"] += (ad.cost or Decimal("0.00"))
        ad_map[(d_str, brand_label)]["ad_rev"]   += (ad.sales_by_conversion or Decimal("0.00"))

    # ---------------------------------------------------------
    # (F) 날짜+브랜드별 결합
    date_brand_map = defaultdict(dict)
    all_keys = set(daily_map.keys()) | set(ad_map.keys())
    for (d_str, brand_label) in all_keys:
        sold_part = daily_map[(d_str, brand_label)]
        ad_part   = ad_map[(d_str, brand_label)]

        sold_qty = sold_part["sold_items"]
        net_s = sold_part["net_sales"]
        purchase_c = sold_part["purchase_cost"]
        etc_c = sold_part["etc_cost"]

        ad_sold = ad_part["ad_sold"]
        ad_sp = ad_part["ad_spend"]
        ad_rev = ad_part["ad_rev"]

        commission = net_s * Decimal("0.04")
        profit_val = net_s - commission - ad_sp - purchase_c - etc_c
        margin_rate = (profit_val / net_s * 100) if net_s else 0

        date_brand_map[d_str][brand_label] = {
            "kind": brand_label,
            "qty": sold_qty,
            "ad_qty": ad_sold,
            "net_sales_amount": net_s,
            "commission": commission,
            "ad_spend": ad_sp,
            "purchase_cost": purchase_c,
            "etc_cost": etc_c,
            "profit": profit_val,
            "margin_rate": margin_rate,
        }

    daily_reports = []
    for d_str in sorted(date_brand_map.keys()):
        label_map = date_brand_map[d_str]
        if not label_map:
            continue
        sum_qty    = sum(x["qty"] for x in label_map.values())
        sum_ad_qty = sum(x["ad_qty"] for x in label_map.values())
        sum_net    = sum(x["net_sales_amount"] for x in label_map.values())
        sum_comm   = sum(x["commission"] for x in label_map.values())
        sum_ad_sp  = sum(x["ad_spend"] for x in label_map.values())
        sum_pc     = sum(x["purchase_cost"] for x in label_map.values())
        sum_etc    = sum(x["etc_cost"] for x in label_map.values())
        sum_profit = sum(x["profit"] for x in label_map.values())
        day_margin = (sum_profit / sum_net * 100) if sum_net else 0

        detail_list = list(label_map.values())

        daily_reports.append({
            "date_str": d_str,
            "qty": sum_qty,
            "ad_qty": sum_ad_qty,
            "net_sales_amount": sum_net,
            "commission": sum_comm,
            "ad_spend": sum_ad_sp,
            "purchase_cost": sum_pc,
            "etc_cost": sum_etc,
            "profit": sum_profit,
            "margin_rate": day_margin,
            "details": detail_list,
        })

    # ---------------------------------------------------------
    # (F) 전체 기간 소계
    total_qty         = sum(x["qty"] for x in daily_reports)
    total_ad_qty      = sum(x["ad_qty"] for x in daily_reports)
    total_net_sales   = sum(x["net_sales_amount"] for x in daily_reports)
    total_commission  = sum(x["commission"] for x in daily_reports)
    total_ad_spend    = sum(x["ad_spend"] for x in daily_reports)
    total_purchase    = sum(x["purchase_cost"] for x in daily_reports)
    total_etc_cost    = sum(x["etc_cost"] for x in daily_reports)
    total_profit      = sum(x["profit"] for x in daily_reports)
    overall_margin    = (total_profit / total_net_sales * 100) if total_net_sales else 0

    period_summary = {
        "total_qty": total_qty,
        "total_ad_qty": total_ad_qty,
        "net_sales_amount": total_net_sales,
        "commission": total_commission,
        "ad_spend": total_ad_spend,
        "purchase_cost": total_purchase,
        "etc_cost": total_etc_cost,
        "profit": total_profit,
        "margin_rate": overall_margin,
    }

    # ---------------------------------------------------------
    # (G) 전체 기간 브랜드별 상세
    brand_summary = defaultdict(lambda: {
        "qty": 0,
        "ad_qty": 0,
        "net_sales_amount": Decimal("0.00"),
        "commission": Decimal("0.00"),
        "ad_spend": Decimal("0.00"),
        "purchase_cost": Decimal("0.00"),
        "etc_cost": Decimal("0.00"),
        "profit": Decimal("0.00"),
    })

    for day in daily_reports:
        for det in day["details"]:
            brand = det["kind"]
            brand_summary[brand]["qty"] += det["qty"]
            brand_summary[brand]["ad_qty"] += det["ad_qty"]
            brand_summary[brand]["net_sales_amount"] += det["net_sales_amount"]
            brand_summary[brand]["commission"] += det["commission"]
            brand_summary[brand]["ad_spend"] += det["ad_spend"]
            brand_summary[brand]["purchase_cost"] += det["purchase_cost"]
            brand_summary[brand]["etc_cost"] += det["etc_cost"]
            brand_summary[brand]["profit"] += det["profit"]

    brand_details = {}
    for b, data in brand_summary.items():
        m_rate = (data["profit"] / data["net_sales_amount"] * 100) if data["net_sales_amount"] else 0
        brand_details[b] = {
            "qty": data["qty"],
            "ad_qty": data["ad_qty"],
            "net_sales_amount": data["net_sales_amount"],
            "commission": data["commission"],
            "ad_spend": data["ad_spend"],
            "purchase_cost": data["purchase_cost"],
            "etc_cost": data["etc_cost"],
            "profit": data["profit"],
            "margin_rate": m_rate,
        }
    period_summary["brand_details"] = brand_details

    # ---------------------------------------------------------
    # (H) 모달용: 일자별 상품별 상세 데이터
    from collections import defaultdict, OrderedDict
    day_p_o_map = defaultdict(lambda: {
        "sold_qty": 0,
        "sales_amt": Decimal("0.00"),
        "ad_qty": 0,
        "ad_spend": Decimal("0.00"),
        "ad_revenue": Decimal("0.00"),
        "click": 0,
        "purchase_cost": Decimal("0.00"),
        "etc_cost": Decimal("0.00"),
    })

    for ds in daily_sales_qs:
        day_str = ds.date if isinstance(ds.date, str) else ds.date.strftime("%Y-%m-%d")
        pid = (ds.product_id or "").strip()
        final_qty = ds.sales_qty - ds.refunded_qty
        final_rev = ds.sales_revenue - ds.refunded_revenue
        key = (day_str, pid)
        day_p_o_map[key]["sold_qty"] += final_qty
        day_p_o_map[key]["sales_amt"] += Decimal(final_rev)
        sku = (ds.option_id or "").strip()
        try:
            cost_obj = NaverPurchaseCost.objects.get(sku_id=sku)
            unit_price = cost_obj.purchasing_price
        except NaverPurchaseCost.DoesNotExist:
            unit_price = Decimal("0.00")
        day_p_o_map[key]["purchase_cost"] += unit_price * final_qty
        day_p_o_map[key]["etc_cost"] += Decimal("0.00")

    for ad in ad_report_qs:
        day_str = ad.date.strftime("%Y-%m-%d") if ad.date else ""
        key_sp = (ad.ad_group_id, ad.ad_id)
        sp_info = sp_map.get(key_sp)
        if not sp_info:
            continue
        pid = (sp_info["product_id_of_mall"] or "").strip()
        if not pid:
            continue
        key = (day_str, pid)
        day_p_o_map[key]["ad_qty"] += (ad.conversion_count or 0)
        day_p_o_map[key]["ad_spend"] += (ad.cost or Decimal("0.00"))
        day_p_o_map[key]["ad_revenue"] += (ad.sales_by_conversion or Decimal("0.00"))
        day_p_o_map[key]["click"] += (ad.click or 0)

    day_products_map = defaultdict(lambda: OrderedDict())
    for (day_str, pid), vals in day_p_o_map.items():
        sold_qty = vals["sold_qty"]
        sales_amt = vals["sales_amt"]
        ad_qty = vals["ad_qty"]
        ad_spend = vals["ad_spend"]
        ad_rev = vals["ad_revenue"]
        clicks = vals["click"]
        pcost = vals["purchase_cost"]
        etc_c = vals["etc_cost"]

        commission = sales_amt * Decimal("0.04")
        profit_val = sales_amt - commission - ad_spend - pcost - etc_c
        margin_rate_val = (profit_val / sales_amt * 100) if sales_amt else 0
        roas_val = (ad_rev / ad_spend * 100) if ad_spend else 0
        ad_sales_rate_val = (ad_qty / sold_qty * 100) if sold_qty else 0
        conv_rate_val = (ad_qty / clicks * 100) if clicks else 0

        product_name = naver_item_map.get(pid, f"(상품:{pid})")
        if pid not in day_products_map[day_str]:
            day_products_map[day_str][pid] = {
                "product_name": product_name,
                "sold_qty": 0,
                "ad_qty": 0,
                "sales_amt": Decimal("0.00"),
                "ad_spend": Decimal("0.00"),
                "ad_revenue": Decimal("0.00"),
                "profit": Decimal("0.00"),
                "roas": 0,
                "ad_sales_rate": 0,
                "click": 0,
                "conversion_rate": 0,
                "purchase_cost": Decimal("0.00"),
                "etc_cost": Decimal("0.00"),
                "margin_rate": 0,
                "commission": Decimal("0.00"),
            }
        rec = day_products_map[day_str][pid]
        rec["sold_qty"] += sold_qty
        rec["sales_amt"] += sales_amt
        rec["ad_qty"] += ad_qty
        rec["ad_spend"] += ad_spend
        rec["ad_revenue"] += ad_rev
        rec["click"] += clicks
        rec["purchase_cost"] += pcost
        rec["etc_cost"] += etc_c
        rec["commission"] = commission
        rec["profit"] = rec["sales_amt"] - rec["commission"] - rec["ad_spend"] - rec["purchase_cost"] - rec["etc_cost"]
        rec["margin_rate"] = (rec["profit"] / rec["sales_amt"] * 100) if rec["sales_amt"] else 0
        rec["roas"] = (rec["ad_revenue"] / rec["ad_spend"] * 100) if rec["ad_spend"] else 0
        rec["ad_sales_rate"] = (rec["ad_qty"] / rec["sold_qty"] * 100) if rec["sold_qty"] else 0
        rec["conversion_rate"] = (rec["ad_qty"] / rec["click"] * 100) if rec["click"] else 0

    for day_str in list(day_products_map.keys()):
        for pid in list(day_products_map[day_str].keys()):
            rec = day_products_map[day_str][pid]
            if (rec["sold_qty"] == 0 and rec["ad_qty"] == 0 and rec["sales_amt"] == 0 and
                rec["ad_spend"] == 0 and rec["ad_revenue"] == 0 and rec["profit"] == 0 and
                rec["purchase_cost"] == 0 and rec["etc_cost"] == 0):
                del day_products_map[day_str][pid]
        if not day_products_map[day_str]:
            del day_products_map[day_str]

    import json
    def convert_keys(obj):
        if isinstance(obj, dict):
            return {str(k): convert_keys(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_keys(item) for item in obj]
        elif isinstance(obj, Decimal):
            return float(obj)
        else:
            return obj

    day_products_map_json = json.dumps(convert_keys(day_products_map), ensure_ascii=False)

    # ---------------------------------------------------------
    # (9) 전체 기간 상품별 상세 데이터 (overall_products_map)
    overall_products_map = defaultdict(lambda: {
        "sold_qty": 0,
        "sales_amt": Decimal("0.00"),
        "ad_qty": 0,
        "ad_spend": Decimal("0.00"),
        "ad_revenue": Decimal("0.00"),
        "purchase_cost": Decimal("0.00"),
        "etc_cost": Decimal("0.00"),
        "store": "N/A"  # store 기본값 추가
    })

    for ds in daily_sales_qs:
        pid = (ds.product_id or "").strip()
        final_qty = ds.sales_qty - ds.refunded_qty
        final_rev = ds.sales_revenue - ds.refunded_revenue
        sku = (ds.option_id or "").strip()
        try:
            cost_obj = NaverPurchaseCost.objects.get(sku_id=sku)
            unit_price = cost_obj.purchasing_price
        except NaverPurchaseCost.DoesNotExist:
            unit_price = Decimal("0.00")
        purchase_val = unit_price * final_qty
        overall_products_map[pid]["sold_qty"] += final_qty
        overall_products_map[pid]["sales_amt"] += Decimal(final_rev)
        overall_products_map[pid]["purchase_cost"] += purchase_val
        overall_products_map[pid]["etc_cost"] += Decimal("0.00")
        if overall_products_map[pid]["store"] == "N/A":
            overall_products_map[pid]["store"] = ds.store
            
    for ad in ad_report_qs:
        key_sp = (ad.ad_group_id, ad.ad_id)
        sp_info = sp_map.get(key_sp)
        if not sp_info:
            continue
        pid = (sp_info.get("product_id_of_mall") or "").strip()
        overall_products_map[pid]["ad_qty"] += (ad.conversion_count or 0)
        overall_products_map[pid]["ad_spend"] += (ad.cost or Decimal("0.00"))
        overall_products_map[pid]["ad_revenue"] += (ad.sales_by_conversion or Decimal("0.00"))

    overall_details = []
    for pid, data in overall_products_map.items():
        commission_val = data["sales_amt"] * Decimal("0.04")
        profit_val = data["sales_amt"] - commission_val - data["ad_spend"] - data["purchase_cost"] - data["etc_cost"]
        margin_rate_val = (profit_val / data["sales_amt"] * 100) if data["sales_amt"] else 0
        roas_val = (data["ad_revenue"] / data["ad_spend"] * 100) if data["ad_spend"] else 0
        ad_sales_rate_val = (data["ad_qty"] / data["sold_qty"] * 100) if data["sold_qty"] else 0
        product_name = naver_item_map.get(pid, f"(상품:{pid})")
        overall_details.append({
            "product_id": pid,
            "product_name": product_name,
            "store": data.get("store", "N/A"),  # store 추가
            "sold_qty": data["sold_qty"],
            "sales_amt": data["sales_amt"],
            "ad_qty": data["ad_qty"],
            "commission": commission_val,  # 수정된 부분: data["commission_val"] → commission_val
            "ad_spend": data["ad_spend"],
            "ad_revenue": data["ad_revenue"],
            "purchase_cost": data["purchase_cost"],
            "etc_cost": data["etc_cost"],
            "profit": profit_val,
            "margin_rate": margin_rate_val,
            "roas": roas_val,
            "ad_sales_rate": ad_sales_rate_val,
        })

    overall_details = [
        od for od in overall_details
        if not (od["sold_qty"] == 0 and od["ad_qty"] == 0 and od["sales_amt"] == 0 and
                od["ad_spend"] == 0 and od["ad_revenue"] == 0 and od["profit"] == 0 and
                od["purchase_cost"] == 0)
    ]
    overall_products_map_json = json.dumps(convert_keys(overall_details), ensure_ascii=False)


    # --- (10) KPI 3종 (예시)
    kpi_list = []
    for prod_key, pinfo in overall_products_map.items():
        commission_val = pinfo["sales_amt"] * Decimal("0.04")
        profit_val = pinfo["sales_amt"] - commission_val - pinfo["ad_spend"] - pinfo["purchase_cost"] - pinfo["etc_cost"]
        margin_rate_val = (profit_val / pinfo["sales_amt"] * 100) if pinfo["sales_amt"] else 0
        product_name = naver_item_map.get(prod_key, f"(상품:{prod_key})")

        kpi_list.append({
            "product_name": product_name,
            "store": pinfo.get("store", "N/A"),   # store 값 표시
            "qty": pinfo["sold_qty"],
            "ad_qty": pinfo["ad_qty"],
            "net_sales_amount": pinfo["sales_amt"],
            "ad_spend": pinfo["ad_spend"],
            "purchase_cost": pinfo["purchase_cost"],
            "profit": profit_val,
            "margin_rate": margin_rate_val,
        })

    # 예시: 마진이 -1% 이하인 상품, 순수익 +1만원 이상, 순수익 -1만원 이하 등으로 필터링
    kpi_margin_low = [x for x in kpi_list if x["margin_rate"] <= -1]
    kpi_profit_high = [x for x in kpi_list if x["profit"] >= 10000]
    kpi_profit_low = [x for x in kpi_list if x["profit"] <= -10000]

    # ---------------------------------------------------------
    # (11) 컨텍스트 및 렌더링
    context = {
        "start_date": start_d,
        "end_date": end_d,
        # 일자별 요약
        "daily_reports": daily_reports,
        "period_summary": period_summary,

        # KPI
        "kpi_margin_low": kpi_margin_low,
        "kpi_profit_high": kpi_profit_high,
        "kpi_profit_low": kpi_profit_low,

        # 모달용
        "day_products_map_json": day_products_map_json,
        "overall_products_map_json": overall_products_map_json
    }

    return render(request, "sales_management/naver_profit_report.html", context)


from .models import NaverPurchaseCost

def naver_update_costs_from_seller_tool_view(request):
    """
    1) naverItem의 optioncode를 수집합니다.
    2) 셀러툴 API를 호출하여 (optioncode -> totalPurchasePrice) 매핑 정보를 가져옵니다.
    3) 모든 naverItem을 순회하면서, skuID와 optioncode 기준으로 NaverPurchaseCost를 update_or_create합니다.
       - 매입가(purchasing_price)는 API에서 받은 totalPurchasePrice로 저장됩니다.
    """
    try:
        # (A) 옵션코드 수집
        items = naverItem.objects.all()
        option_codes = {it.optioncode for it in items if it.optioncode}
        logger.info(f"[update_costs_from_seller_tool_view] option_codes 개수={len(option_codes)}")
        
        if not option_codes:
            messages.warning(request, "옵션코드가 없습니다.")
            return redirect('profit_report')
        
        # (B) 셀러툴 API 호출 및 결과 처리
        option_codes = list(option_codes)
        result_data = fetch_seller_tool_option_info(option_codes)
        content_list = result_data.get("content", [])
        logger.info(f"[update_costs_from_seller_tool_view] content_list len={len(content_list)}")
        
        # (B-1) optioncode -> totalPurchasePrice 매핑 딕셔너리 생성
        code_to_price = {}
        for row in content_list:
            code = row.get("code")
            price = row.get("totalPurchasePrice", 0)
            if code:
                code_to_price[code] = price
        
        # (C) naverItem 순회하여 매입가 업데이트
        updated_count = 0
        created_count = 0
        
        for it in items:
            if it.skuID:  # [수정] 조건문에 콜론 추가
                sku_id_val = it.skuID
                option_code_val = it.optioncode
                # API에서 받은 매입가, 기본값 0
                purchase_val = code_to_price.get(option_code_val, 0)
                
                obj, created_flag = NaverPurchaseCost.objects.update_or_create(
                    sku_id=sku_id_val,
                    option_code=option_code_val,
                    defaults={"purchasing_price": purchase_val}
                )
                if created_flag:
                    created_count += 1
                    logger.info(f"NEW: sku_id={sku_id_val}, option_code={option_code_val}, price={purchase_val}")
                else:
                    updated_count += 1
                    logger.info(f"UPD: sku_id={sku_id_val}, option_code={option_code_val}, price={purchase_val}")
        
        messages.success(
            request,
            f"매입가 업데이트 완료! (생성: {created_count}건, 업데이트: {updated_count}건)"
        )
    
    except Exception as e:
        logger.exception("[update_costs_from_seller_tool_view] 오류:")
        messages.error(request, f"에러 발생: {str(e)}")
    
    return redirect('naver_profit_report')

