# coupang_sales/views.py
from django.shortcuts import render
from django.http import JsonResponse
import logging
from django.utils import timezone
from datetime import datetime
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import CoupangProduct, CoupangItem, CoupangItemImage


from .api_clients import COUPANG_ACCOUNTS, fetch_coupang_all_seller_products, get_coupang_seller_product

logger = logging.getLogger(__name__)


def group_management_view(request):
    return render(request, 'coupang_sales/group_management.html')

# 상품리스트 시작


def product_list_view(request):
    products = CoupangProduct.objects.all().prefetch_related('items')

    # (A) 상품 단위: 로켓&판매자 / 로켓그로스 / 판매자배송
    # (B) 각 item도 "로켓그로스" or "판매자배송" 표시
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

    # (C) 딕셔너리 형태(grouped_data)로 [상품ID -> { 'product':..., 'items':... }] 구성
    grouped_data = {}
    for prod in products:
        spid = prod.sellerProductId
        if spid not in grouped_data:
            grouped_data[spid] = {
                'product': prod,
                'items': prod.items.all()
            }

    # (D) 계산 로직: salePrice, originalPrice, fee(수수료), profit(개당이익금) 등
    fee_rate = 0.1188

    for product in products:
        # 1) 상위행 표시용 (첫 번째 item 기준)
        first_item = product.items.first()
        if first_item:
            # sale_price
            if first_item.rocket_sale_price is not None and first_item.rocket_sale_price > 0:
                top_sale_price = first_item.rocket_sale_price
            elif first_item.marketplace_sale_price is not None and first_item.marketplace_sale_price > 0:
                top_sale_price = first_item.marketplace_sale_price
            else:
                top_sale_price = 0

            # original_price
            if first_item.rocket_original_price is not None and first_item.rocket_original_price > 0:
                top_original_price = first_item.rocket_original_price
            elif first_item.marketplace_original_price is not None and first_item.marketplace_original_price > 0:
                top_original_price = first_item.marketplace_original_price
            else:
                top_original_price = 0

            # 마켓 수수료, 개당이익금
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

        # 2) 하위행(옵션) 계산
        for item in product.items.all():
            # sale_price
            if item.rocket_sale_price is not None and item.rocket_sale_price > 0:
                i_sale_price = item.rocket_sale_price
            elif item.marketplace_sale_price is not None and item.marketplace_sale_price > 0:
                i_sale_price = item.marketplace_sale_price
            else:
                i_sale_price = 0

            # original_price
            if item.rocket_original_price is not None and item.rocket_original_price > 0:
                i_original_price = item.rocket_original_price
            elif item.marketplace_original_price is not None and item.marketplace_original_price > 0:
                i_original_price = item.marketplace_original_price
            else:
                i_original_price = 0

            # 수수료, 이익
            i_fee = i_sale_price * fee_rate if i_sale_price > 0 else 0
            i_profit = i_sale_price - i_fee if i_sale_price > 0 else 0

            item.calc_sale_price = i_sale_price
            item.calc_original_price = i_original_price
            item.calc_fee = i_fee
            item.calc_profit = i_profit

            # 추가: externalVendorSku 관련 필드 계산
            item.rocket_external_vendor_sku = item.rocket_external_vendor_sku or "-"
            item.marketplace_external_vendor_sku = item.marketplace_external_vendor_sku or "-"

    context = {
        'products': products,
        'grouped_data': grouped_data,  # 꼭 추가
    }
    return render(request, 'coupang_sales/product_list.html', context)



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
    쿠팡 상품데이터를 업데이트하기 위한 액션 뷰.
    1) fetch_coupang_all_seller_products 호출 → sellerProductId 목록 가져옴
    2) 각 sellerProductId에 대해 get_coupang_seller_product 호출 → 상세정보 DB 저장
    """
    if request.method == 'POST':
        # 예: 첫 번째 계정으로만 업데이트 (필요 시, 다른 계정도 선택 가능하게 로직 확장)
        account_info = COUPANG_ACCOUNTS[0]

        success, product_list = fetch_coupang_all_seller_products(account_info)
        if not success:
            # product_list 안에 에러 메시지 들어있을 것
            messages.error(request, f"쿠팡 상품 목록 조회 실패: {product_list}")
            return redirect('product_list')

        # product_list는 [{"sellerProductId":..., ...}, {...}, ...] 형태
        count_ok = 0
        for product in product_list:
            seller_product_id = product.get('sellerProductId')
            if not seller_product_id:
                continue

            success_detail, detail_data = get_coupang_seller_product(account_info, seller_product_id)
            if success_detail:
                # detail_data = {"sellerProductId": ..., "items": [...], ...}
                _save_coupang_product_detail(detail_data)
                count_ok += 1
            else:
                # detail_data 안에 에러 메시지가 있을 수도 있음
                messages.warning(request, f"상세 조회 실패 - ID={seller_product_id}, reason={detail_data}")

        messages.success(request, f"총 {count_ok}개 상품 상세정보를 업데이트했습니다.")
        return redirect('product_list')
    else:
        # GET 등 다른 요청이면 단순히 상품 리스트로 리다이렉트
        return redirect('product_list')


def _save_coupang_product_detail(data):
    """
    API 응답(JSON)으로부터 
    - CoupangProduct (sellerProductId 등)
    - CoupangItem (rocket_* / marketplace_* ...)
    - CoupangItemImage (images)
    를 DB에 생성.
    
    여기서 'custom id' = 'externalVendorSku'를 각각
    rocket_external_vendor_sku / marketplace_external_vendor_sku 로 저장함.
    """

    from .models import CoupangProduct, CoupangItem, CoupangItemImage

    # 1) 상위 레코드 (CoupangProduct)
    product_obj = CoupangProduct.objects.create(
        code = data.get('code', ''),
        message = data.get('message', ''),

        sellerProductId = data.get('sellerProductId'),
        sellerProductName = data.get('sellerProductName'),
        displayCategoryCode = data.get('displayCategoryCode'),
        vendorId = data.get('vendorId'),
        brand = data.get('brand'),
        productGroup = data.get('productGroup'),
        statusName = data.get('statusName'),
        vendorUserId = data.get('vendorUserId'),
        requested = data.get('requested', False),
    )

    # 2) items 배열
    items_list = data.get('items', [])
    for item_data in items_list:
        # (A) rocketGrowthItemData
        rocket_data = item_data.get('rocketGrowthItemData', {})
        rocket_sku_info = rocket_data.get('skuInfo', {})
        rocket_price_data = rocket_data.get('priceData', {})

        # (B) marketplaceItemData
        marketplace_data = item_data.get('marketplaceItemData', {})
        marketplace_price_data = marketplace_data.get('priceData', {})

        # ★ rocket externalVendorSku
        if rocket_data:
            rocket_external_vendor_sku = rocket_data.get('externalVendorSku', None)
        else:
            # 만약 rocketData가 없으면 item_data["externalVendorSku"]가 있을 수 있으면 fallback
            rocket_external_vendor_sku = item_data.get('externalVendorSku', None)

        # ★ marketplace externalVendorSku
        if marketplace_data:
            marketplace_external_vendor_sku = marketplace_data.get('externalVendorSku', None)
        else:
            # fallback
            marketplace_external_vendor_sku = item_data.get('externalVendorSku', None)

        # -------------------------
        # 로켓 관련 필드 없는 경우 처리
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

        # -------------------------
        # 마켓 관련 필드 없는 경우 처리
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

        # 2) CoupangItem 생성 (custom ID = externalVendorSku)
        item_obj = CoupangItem.objects.create(
            parent = product_obj,

            itemName = item_data.get('itemName'),
            unitCount = item_data.get('unitCount', 1),
            outboundShippingTime = item_data.get('outboundShippingTime', 0),

            # rocket_*
            rocket_seller_product_item_id = rocket_seller_product_item_id,
            rocket_vendor_item_id = rocket_vendor_item_id,
            rocket_item_id = rocket_item_id,
            rocket_barcode = rocket_barcode,
            rocket_model_no = rocket_model_no,
            rocket_original_price = rocket_original_price,
            rocket_sale_price = rocket_sale_price,
            rocket_supply_price = rocket_supply_price,
            rocket_height = rocket_height,
            rocket_length = rocket_length,
            rocket_width = rocket_width,
            rocket_weight = rocket_weight,
            rocket_quantity_per_box = rocket_quantity_per_box,
            rocket_stand_alone = rocket_stand_alone,
            rocket_distribution_period = rocket_distribution_period,
            rocket_expired_at_managed = rocket_expired_at_managed,
            rocket_manufactured_at_managed = rocket_manufactured_at_managed,
            rocket_net_weight = rocket_net_weight,
            rocket_heat_sensitive = rocket_heat_sensitive,
            rocket_hazardous = rocket_hazardous,
            rocket_original_barcode = rocket_original_barcode,
            rocket_maximum_buy_count = item_data.get('maximumBuyCount', 0),  # 예시
            rocket_inbound_name = rocket_inbound_name,
            rocket_original_dimension_input_type = rocket_original_dimension_input_type,

            # ★ 로켓 custom ID
            rocket_external_vendor_sku = rocket_external_vendor_sku,

            # marketplace_*
            marketplace_seller_product_item_id = mk_seller_product_item_id,
            marketplace_vendor_item_id = mk_vendor_item_id,
            marketplace_item_id = mk_item_id,
            marketplace_barcode = mk_barcode,
            marketplace_model_no = mk_model_no,
            marketplace_best_price_guaranteed_3p = mk_best_price_3p,
            marketplace_original_price = mk_original_price,
            marketplace_sale_price = mk_sale_price,
            marketplace_supply_price = mk_supply_price,
            marketplace_maximum_buy_count = item_data.get('maximumBuyCount', 0),  # 예시

            # ★ 마켓 custom ID
            marketplace_external_vendor_sku = marketplace_external_vendor_sku,
        )

        # 3) images
        images_array = item_data.get('images', [])
        for img_data in images_array:
            CoupangItemImage.objects.create(
                parent_item = item_obj,
                imageOrder = img_data.get('imageOrder', 0),
                imageType = img_data.get('imageType'),
                cdnPath = img_data.get('cdnPath'),
                vendorPath = img_data.get('vendorPath'),
            )

    return product_obj














def dashboard_view(request):
    return render(request, 'coupang_sales/dashboard.html')

def sales_report_view(request):
    return render(request, 'coupang_sales/sales_report.html')

def ad_report_view(request):
    return render(request, 'coupang_sales/ad_report.html')

def profit_loss_view(request):
    return render(request, 'coupang_sales/profit_loss.html')
