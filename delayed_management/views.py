import openpyxl
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import DelayedOrderUploadForm, OptionStoreMappingUploadForm  
from .models import DelayedOrder, ProductOptionMapping ,OptionStoreMapping, DelayedShipment,DelayedShipmentGroup,ExternalPlatformMapping,ExternalProductItem,ExternalProductOption, OptionMapping,OptionPlatformDetail,OutOfStockMapping
from django.core.paginator import Paginator
from .api_clients import get_exchangeable_options,get_option_info_by_code,get_all_options_by_product_name,get_options_detail_by_codes,get_inventory_by_option_codes,fetch_coupang_seller_product_with_options,NAVER_ACCOUNTS,COUPANG_ACCOUNTS
from .spreadsheet_utils import read_spreadsheet_data
from datetime import date, timedelta, datetime
from django.conf import settings
from .spreadsheet_utils import get_gspread_client
import uuid
import hmac
import hashlib
from decouple import config
import logging
import requests
import gspread
from django.http import HttpResponse
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
import json
from django.views.decorators.http import require_POST


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 필요 시 레벨 지정

# ==========================
# 1) "업로드" + "리스트 업로드" 함수
# ==========================
def upload_delayed_orders(request):
    print("=== DEBUG: upload_delayed_orders 뷰 진입 ===")

    # (A) 엑셀 업로드 (임시 세션 저장)
    if request.method == 'POST' and 'upload_excel' in request.POST:
        form = DelayedOrderUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active

            temp_orders = []
            for idx, row in enumerate(ws.iter_rows(values_only=True)):
                if idx == 0:
                    # 첫 행(헤더) 스킵
                    continue
                if not row or len(row) < 11:
                    # 컬럼 부족 등 스킵
                    continue

                option_code         = (row[0] or "").strip()
                customer_name       = (row[1] or "").strip()
                customer_contact    = (row[2] or "").strip()
                order_product_name  = (row[3] or "").strip()
                order_option_name   = (row[4] or "").strip()
                quantity            = (row[5] or "").strip()
                seller_product_name = (row[6] or "").strip()
                seller_option_name  = (row[7] or "").strip()
                order_number_1      = (row[8] or "").strip()
                order_number_2      = (row[9] or "").strip()  # 필요하다면 남김
                store_name_raw      = (row[10] or "").strip()

                # 옵션코드 / 주문번호1이 반드시 있어야 한다고 가정
                if not option_code:
                    print("=== DEBUG: 옵션코드 없음, 스킵 ===")
                    continue
                if not order_number_1:
                    print("=== DEBUG: 주문번호1 없음, 스킵 ===")
                    continue

                order_data = {
                    'option_code': option_code,
                    'customer_name': customer_name,
                    'customer_contact': customer_contact,
                    'order_product_name': order_product_name,
                    'order_option_name': order_option_name,
                    'quantity': quantity,
                    'seller_product_name': seller_product_name,
                    'seller_option_name': seller_option_name,
                    'order_number_1': order_number_1,
                    'order_number_2': order_number_2,  # 필요에 따라 사용
                    'store_name': store_name_raw,
                }
                temp_orders.append(order_data)

            # 세션에 임시저장
            request.session['delayed_orders_temp'] = temp_orders
            messages.success(request, f"{len(temp_orders)}건이 임시로 업로드되었습니다.")
            return redirect('upload_delayed_orders')
        else:
            messages.error(request, "파일 업로드 실패.")
            return redirect('upload_delayed_orders')

    # (B) 최종 DB 저장 + 자동처리
    elif request.method == 'POST' and 'finalize' in request.POST:
        temp_orders = request.session.get('delayed_orders_temp', [])
        if not temp_orders:
            messages.error(request, "임시 데이터가 없습니다.")
            return redirect('upload_delayed_orders')

        # 1) 기존 DB에서 'order_number_1' 목록 추출 → 중복 체크용
        existing_orders = set(
            DelayedShipment.objects.values_list('order_number_1', flat=True)
        )
        print(f"=== DEBUG: DB 내 이미 존재하는 주문번호1 개수: {len(existing_orders)}")

        success_count = 0
        fail_count = 0
        newly_created_ids = []

        # 업로드 실패 항목만 남길 임시배열
        remaining_temp_orders = []

        from collections import defaultdict
        group_token_map = defaultdict(lambda: str(uuid.uuid4()))

        # 2) temp_orders 순회, 중복 검사
        for od in temp_orders:
            order_num_1 = od.get('order_number_1', '')

            if not order_num_1:
                # 주문번호1 없으면 실패 처리
                fail_count += 1
                remaining_temp_orders.append(od)
                continue

            if order_num_1 in existing_orders:
                # 이미 DB에 존재하면 실패 처리
                fail_count += 1
                remaining_temp_orders.append(od)
                continue

            # 3) 중복 아니면 DB 저장
            #    그룹핑 기준: (주문번호1 + customer_name + customer_contact)
            group_key = (
                od['order_number_2'].strip(),
                od['customer_name'].strip(),
                od['customer_contact'].strip()
            )
            group_token = group_token_map[group_key]

            shipment = DelayedShipment.objects.create(
                option_code         = od['option_code'],
                customer_name       = od['customer_name'],
                customer_contact    = od['customer_contact'],
                order_product_name  = od['order_product_name'],
                order_option_name   = od['order_option_name'],
                quantity            = od['quantity'],
                seller_product_name = od['seller_product_name'],
                seller_option_name  = od['seller_option_name'],
                order_number_1      = od['order_number_1'],
                order_number_2      = od['order_number_2'],  # 필요 시 저장
                store_name          = od['store_name'],
                token               = group_token,
            )
            newly_created_ids.append(shipment.id)
            success_count += 1

            # 새로 등록된 order_number_1 추가
            existing_orders.add(order_num_1)

        # 4) 세션에는 실패 항목만 남긴다
        request.session['delayed_orders_temp'] = remaining_temp_orders

        print(f"=== DEBUG: 업로드 성공 {success_count}건 / 실패 {fail_count}건 ===")

        # (자동 처리) 옵션추출 + 스토어매핑 + 재입고동기화
        if newly_created_ids:
            extract_options_for_ids(newly_created_ids)
            store_mapping_for_ids(newly_created_ids)
            update_restock_from_sheet(request)  # <= "스프레드시트 기반 상태/날짜 동기화"

        # 5) 결과 메시지를 표시하고 템플릿을 다시 렌더
        messages.success(
            request,
            (
                f"총 {len(temp_orders)}건 중 저장 성공 {success_count}건, 실패 {fail_count}건\n"
                "(실패 항목은 테이블에 남아있음)"
            )
        )
        return render(request, 'delayed_management/upload_delayed_orders.html', {
            'form': DelayedOrderUploadForm(),
            'temp_orders': remaining_temp_orders,  # 실패한 항목
        })

    # (C) 임시 데이터 중 하나 삭제
    elif request.method == 'POST' and 'delete_item' in request.POST:
        temp_orders = request.session.get('delayed_orders_temp', [])
        index_to_delete = request.POST.get('delete_index')
        if index_to_delete is not None:
            try:
                idx = int(index_to_delete)
                if 0 <= idx < len(temp_orders):
                    deleted_item = temp_orders[idx]
                    del temp_orders[idx]
                    request.session['delayed_orders_temp'] = temp_orders
                    messages.success(request, f"{deleted_item['option_code']} 항목이 삭제되었습니다.")
                else:
                    messages.error(request, "잘못된 인덱스입니다.")
            except ValueError:
                messages.error(request, "잘못된 요청입니다.")
        return redirect('upload_delayed_orders')
    
    # **(C-2) 임시 데이터 전체 삭제** ← 새로 추가할 부분
    elif request.method == 'POST' and 'delete_all_items' in request.POST:
        request.session['delayed_orders_temp'] = []
        messages.success(request, "테이블 전체가 삭제되었습니다.")
        return redirect('upload_delayed_orders')


    # (D) GET: 업로드 폼 표시
    else:
        temp_orders = request.session.get('delayed_orders_temp', [])
        return render(request, 'delayed_management/upload_delayed_orders.html', {
            'form': DelayedOrderUploadForm(),
            'temp_orders': temp_orders,
        })




# ==========================
# 2) 하위 처리 함수들
# ==========================
def extract_options_for_ids(shipment_ids):
    qs = DelayedShipment.objects.filter(id__in=shipment_ids)
    if not qs.exists():
        return

    for shipment in qs:
        # (1) needed_qty 계산
        try:
            needed_qty = int(shipment.quantity or '1')
        except ValueError:
            needed_qty = 1

        # (2) get_exchangeable_options() → [{"optionName":..., "optionCode":..., "stock":...}, ...]
        exchange_list = get_exchangeable_options(shipment.option_code, needed_qty=needed_qty)

        if not exchange_list:
            # 결과가 아예 없으면 '상담원 문의'
            shipment.exchangeable_options = "상담원 문의"
            shipment.save()
            continue

        # (3) JSON 배열 → optionName 들만 뽑아서 콤마 문자열 생성
        #     예: ['애쉬그레이(R)', '샌드카키(L)', ...]
        name_list = [item["optionName"] for item in exchange_list]
        final_str = ",".join(name_list)  # "애쉬그레이(R),샌드카키(L),..."

        # (4) DB 저장
        shipment.exchangeable_options = final_str
        shipment.save()



def store_mapping_for_ids(shipment_ids):
    """
    새로 생성된 DelayedShipment 레코드들(ID 목록)에 대해
    store_name 매핑을 수행 (option_code → OptionStoreMapping).
    """
    qs = DelayedShipment.objects.filter(id__in=shipment_ids)
    if not qs.exists():
        return  # 아무것도 없으면 끝

    for shipment in qs:
        code = shipment.option_code
        try:
            osm = OptionStoreMapping.objects.get(option_code=code)
            shipment.store_name = osm.store_name
        except OptionStoreMapping.DoesNotExist:
            shipment.store_name = ""
        shipment.save()


def update_restock_from_sheet(request):
    service_account_file = settings.SERVICE_ACCOUNT_FILE
    spreadsheet_id = "xxxxxx..."
    client = get_gspread_client(service_account_file)
    sh = client.open_by_key(spreadsheet_id)

    tabs = ["구매된상품들", "배송중", "도착완료", "서류작성", "선적중"]
    today = date.today()
    total_updated = 0

    for tab_name in tabs:
        try:
            worksheet = sh.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            print(f"=== 시트 '{tab_name}' 없음, 건너뜁니다.")
            continue

        data = worksheet.get_all_values()
        for idx, row in enumerate(data[1:], start=2):
            if not row or len(row) < 1:
                continue

            option_code = (row[0] or "").strip()
            if not option_code:
                continue

            # 스프레드시트 탭 → DB status
            status_code = map_status(tab_name)

            # ETA 계산 (min_days만 사용)
            min_days, max_days = ETA_RANGES.get(status_code, (0,0))
            calc_date = today + timedelta(days=min_days) if min_days else None

            # 기존처럼 get() → MultipleObjectsReturned 가능
            # → filter()로 전부 반영
            qs = DelayedShipment.objects.filter(option_code=option_code)
            if not qs.exists():
                continue

            # 상태+expected_restock_date (bulk update)
            qs.update(
                status=status_code,
                expected_restock_date=calc_date,
            )

            # restock_date가 None인 경우만 새로 설정
            for ship in qs:
                if ship.restock_date is None:
                    ship.restock_date = calc_date
                    ship.save()

            total_updated += qs.count()

    messages.success(request, f"{total_updated}건 동기화 완료")
    return redirect('restock_management')


def post_list_view(request):
    return render(request, 'delayed_management/post_list.html')

def upload_file_view(request):
    print("=== DEBUG: upload_file_view 진입 ===")
    if request.method == 'POST':
        print("=== DEBUG: upload_file_view POST 요청 ===")
    return redirect('upload_delayed_orders')



def upload_store_mapping(request):
    # 1) 검색어(GET 파라미터) 확인
    search_option_code = request.GET.get('search_option_code', '').strip()
    found_store_name = None

    if search_option_code:
        try:
            # 검색 옵션코드가 존재하면 store_name 가져오기
            mapping = OptionStoreMapping.objects.get(option_code=search_option_code)
            found_store_name = mapping.store_name
        except OptionStoreMapping.DoesNotExist:
            # 검색 실패 시 None
            found_store_name = None

    if request.method == 'POST':
        form = OptionStoreMappingUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active

            row_count = 0
            codes_seen = set()
            for idx, row in enumerate(ws.iter_rows(values_only=True)):
                if idx == 0:
                    continue
                if not row or len(row) < 2:
                    continue

                option_code = (row[0] or "").strip()
                store_name = (row[1] or "").strip()

                if not option_code:
                    continue
                if option_code in codes_seen:
                    continue
                codes_seen.add(option_code)

                OptionStoreMapping.objects.update_or_create(
                    option_code=option_code,
                    defaults={'store_name': store_name}
                )
                row_count += 1

            messages.success(request, f"{row_count}건의 스토어명 매핑 정보가 업로드/갱신되었습니다.")
            return redirect('upload_store_mapping')
    else:
        form = OptionStoreMappingUploadForm()

    # 페이지네이션
    mappings_qs = OptionStoreMapping.objects.all().order_by('option_code')
    paginator = Paginator(mappings_qs, 30)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 페이지네이션 범위
    visible_pages = 5
    current = page_obj.number
    total = page_obj.paginator.num_pages

    half = visible_pages // 2
    start_page = current - half
    if start_page < 1:
        start_page = 1
    end_page = start_page + visible_pages - 1
    if end_page > total:
        end_page = total
        start_page = max(end_page - visible_pages + 1, 1)

    page_range_custom = range(start_page, end_page + 1)

    context = {
        'form': form,
        'mappings': page_obj,
        'page_obj': page_obj,
        'page_range_custom': page_range_custom,
        'search_option_code': search_option_code,
        'found_store_name': found_store_name,
    }
    return render(request, 'delayed_management/upload_store_mapping.html', context)


def delete_store_mapping(request, mapping_id):
    if request.method == 'POST':
        mapping = get_object_or_404(OptionStoreMapping, id=mapping_id)
        mapping.delete()
        messages.success(request, "삭제 완료")
    return redirect('upload_store_mapping')


def add_or_update_store_mapping(request):
    if request.method == 'POST':
        option_code = request.POST.get('option_code', '').strip()
        store_name = request.POST.get('store_name', '').strip()

        if option_code and store_name:
            # 이미 존재하면 업데이트
            OptionStoreMapping.objects.update_or_create(
                option_code=option_code,
                defaults={'store_name': store_name}
            )
            messages.success(request, f"옵션코드 {option_code} 스토어명이 업데이트/추가되었습니다.")
        else:
            messages.error(request, "옵션코드와 스토어명을 모두 입력해주세요.")
    return redirect('upload_store_mapping')

def map_stores_for_shipments(request):
    """
    배송지연 목록에서 '스토어 매핑' 버튼을 누르면 실행:
    DelayedShipment.option_code와 OptionStoreMapping.option_code 매칭 → store_name 업데이트
    """
    if request.method == 'POST':
        shipments = DelayedShipment.objects.all()
        count_updated = 0

        for ds in shipments:
            try:
                mapping = OptionStoreMapping.objects.get(option_code=ds.option_code)
                # store_name 업데이트
                ds.store_name = mapping.store_name
                ds.save()
                count_updated += 1
            except OptionStoreMapping.DoesNotExist:
                # 매핑 없으면 스킵
                pass

        messages.success(request, f"스토어 매핑 완료: {count_updated}건이 업데이트되었습니다.")
        return redirect('delayed_shipment_list')

    # GET 요청이면 그냥 목록으로 리다이렉트 (또는 405에러 등)
    return redirect('delayed_shipment_list')


def delayed_shipment_list(request):
    qs = DelayedShipment.objects.filter(flow_status='pre_send').order_by('-created_at')

    today = date.today()
    for s in qs:
        min_days, max_days = ETA_RANGES.get(s.status, (0,0))

        # 고정 안내날짜 range
        if s.restock_date:
            s.range_start = s.restock_date + timedelta(days=min_days)
            s.range_end   = s.restock_date + timedelta(days=max_days)
        else:
            s.range_start = None
            s.range_end   = None

        # 동적 예상날짜 range
        if s.expected_restock_date:
            s.expected_start = s.expected_restock_date + timedelta(days=min_days)
            s.expected_end   = s.expected_restock_date + timedelta(days=max_days)
        else:
            s.expected_start = None
            s.expected_end   = None

    return render(request, 'delayed_management/delayed_shipment_list.html', {
        'shipments': qs
    })


########################################################
# 교환가능옵션 / 스토어매핑 / 선택삭제 / 문자발송 모두를 처리하는 뷰
########################################################

def change_exchangeable_options(request):
    """
    하나의 폼에서 4개 버튼(action)을 구분:
      - extract_options (옵션추출)
      - store_mapping (스토어 매핑)
      - delete_multiple (선택 삭제)
      - send_sms (문자 발송)
    """
    if request.method == 'POST':
        action = request.POST.get('action', '')

        # 1) 옵션추출 로직
        if action == 'extract_options':
            shipment_ids = request.POST.getlist('shipment_ids', [])
            if not shipment_ids:
                messages.error(request, "옵션추출할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            # id__in 으로 필터
            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            updated = 0
            for s in shipments:
                # 교환가능 옵션 조회
                needed_qty = int(s.quantity or 1)
                exchange_list = get_exchangeable_options(s.option_code, needed_qty)
                # 문자열화
                s.exchangeable_options = ",".join(exchange_list) if exchange_list else "상담원 문의"
                s.save()
                updated += 1

            messages.success(request, f"{updated}건 옵션추출 완료.")
            return redirect('delayed_shipment_list')

        # 2) 스토어 매핑 로직
        elif action == 'store_mapping':
            shipment_ids = request.POST.getlist('shipment_ids', [])
            if not shipment_ids:
                messages.error(request, "스토어 매핑할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            updated = 0
            for s in shipments:
                # s.option_code 로 OptionStoreMapping 조회
                try:
                    osm = OptionStoreMapping.objects.get(option_code=s.option_code)
                    s.store_name = osm.store_name
                    s.save()
                    updated += 1
                except OptionStoreMapping.DoesNotExist:
                    # 매핑이 없으면 넘어감 (필요시 처리)
                    pass

            messages.success(request, f"{updated}건 스토어 매핑 완료.")
            return redirect('delayed_shipment_list')

        # 3) 선택 삭제 로직
        elif action == 'delete_multiple':
            shipment_ids = request.POST.getlist('shipment_ids', [])
            if not shipment_ids:
                messages.error(request, "삭제할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            qs = DelayedShipment.objects.filter(id__in=shipment_ids)
            deleted_info = qs.delete()
            total_deleted = deleted_info[0]  # (삭제된 객체 수, {model: 개수})
            return redirect('delayed_shipment_list')

        # 4) 문자 발송 로직
        # 예시) change_exchangeable_options(request) 내부 혹은 send_sms 로직 등에서
        # 'store_name'이 없으면 발송 대상에서 제외하는 로직을 추가

        # (1) 문자 발송 로직
        if action == 'send_sms':
            logger.debug("=== DEBUG: 문자 발송 로직 진입 ===")

            shipment_ids = request.POST.getlist('shipment_ids', [])
            if not shipment_ids:
                messages.error(request, "문자 발송할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            if not shipments.exists():
                messages.error(request, "발송할 데이터가 없습니다.")
                return redirect('delayed_shipment_list')

            messages_list = []
            local_fail_ids = []

            for s in shipments:
                # 스토어명 없으면 => fail
                if not s.store_name:
                    local_fail_ids.append(s.id)
                    s.send_status = 'FAIL'
                    s.save()
                    continue

                # store_name → channel_name → pfId/templateId
                channel_name = map_store_to_channel(s.store_name)
                pf_id = get_pfId_by_channel(channel_name)
                template_id = get_templateId_by_channel(channel_name)

                # 임시로 DB에 SENDING
                if pf_id:
                    s.send_type = 'KAKAO'
                else:
                    s.send_type = 'SMS'
                s.send_status = 'SENDING'
                s.save()

                # 치환변수 등
                min_days, max_days = ETA_RANGES.get(s.status, (0, 0))
                if s.restock_date:
                    start_d = s.restock_date + timedelta(days=min_days)
                    end_d   = s.restock_date + timedelta(days=max_days)
                    발송일자_str = f"{start_d.strftime('%Y.%m.%d')} ~ {end_d.strftime('%m.%d')}"
                else:
                    발송일자_str = "상담원문의"

                url_thx = f"piaarlab.store/delayed/customer-action?action=wait&token={s.token}"
                url_change = f"piaarlab.store/delayed/option-change?action=change&token={s.token}"

                variables = {
                    '#{고객명}': s.customer_name or "",
                    '#{상품명}': s.order_product_name or "",
                    '#{옵션명}': s.order_option_name or "",
                    '#{발송일자}': 발송일자_str,
                    '#{교환옵션명}': s.exchangeable_options or "",
                    '#{채널명}': s.store_name or "",
                    '#{url}': "example.com",
                    '#{url_thx}': url_thx,
                    '#{url_change}': url_change,
                }

                msg = {
                    "to": s.customer_contact or "",
                    "from": SOLAPI_SENDER_NUMBER,
                }
                if pf_id:
                    # 알림톡
                    msg["kakaoOptions"] = {
                        "pfId": pf_id,
                        "templateId": template_id,
                        "variables": variables
                    }
                else:
                    # 문자
                    msg["text"] = (
                        f"[문자 테스트]\n"
                        f"안녕하세요 {s.customer_name or ''}님,\n"
                        f"{s.order_product_name or ''} 제품이 품절되어 연락드립니다. "
                        "스토어로 연락주시면 상품 변경/취소처리를 빠르게 도와드리겠습니다."
                    )

                # customFields에 shipment_id 필수!
                # 웹훅에서 이걸로 DB 매칭
                if "customFields" not in msg:
                    msg["customFields"] = {}
                msg["customFields"]["shipment_id"] = str(s.id)

                # 추가
                messages_list.append((s, msg))

            if not messages_list and not local_fail_ids:
                messages.warning(request, "발송할 대상이 없습니다.")
                return redirect('delayed_shipment_list')

            try:
                logger.debug("=== DEBUG: solapi_send_messages() 호출 전 ===")
                success_list, fail_list, group_id = solapi_send_messages(messages_list)
                logger.debug(f"=== DEBUG: solapi_send_messages() 완료 => success_list={success_list}, fail_list={fail_list}, group_id={group_id}")

                fail_list.extend(local_fail_ids)

                # groupId 저장
                all_sent_ids = [s.id for (s, _) in messages_list]
                DelayedShipment.objects.filter(id__in=all_sent_ids).update(solapi_group_id=group_id)

                # 성공건, 실패건
                DelayedShipment.objects.filter(id__in=success_list).update(flow_status='sent', send_status='SUCCESS')
                DelayedShipment.objects.filter(id__in=fail_list).update(flow_status='pre_send', send_status='FAIL')

                messages.success(request, f"문자 발송 완료 (groupId={group_id})")

            except Exception as e:
                logger.exception("=== DEBUG: 문자 발송 오류 발생 ===")
                messages.error(request, f"문자 발송 오류: {str(e)}")

            return redirect('delayed_shipment_list')


        
        # ★ 새롭게 추가할 "옵션매핑 전송" 로직
        # 5) 옵션매핑 전송 로직
        # (C) "옵션매핑 전송" 버튼 (send_option_mapping)
        elif action == 'send_option_mapping':
            shipment_ids = request.POST.getlist('shipment_ids', [])
            logger.debug(f"[send_option_mapping] shipment_ids={shipment_ids}")  # 1) 체크박스 id들 확인

            if not shipment_ids:
                messages.error(request, "전송할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            logger.debug(f"[send_option_mapping] shipments.count={shipments.count()}")  # 2) 쿼리셋 개수 확인

            if not shipments.exists():
                messages.error(request, "선택된 항목이 없거나 이미 삭제되었습니다.")
                return redirect('delayed_shipment_list')

            updated_count = 0

            for s in shipments:
                # 각 DelayedShipment의 주요 필드 값 로그
                logger.debug(
                    f"[send_option_mapping] DelayedShipment id={s.id}, "
                    f"option_code={s.option_code}, status={s.status}, "
                    f"expected_restock_date={s.expected_restock_date}, "
                    f"seller_option_name={s.seller_option_name}"
                )

                # (A) 예상날짜(ETA_RANGES 등) 계산
                min_days, max_days = ETA_RANGES.get(s.status, (0, 0))
                if s.expected_restock_date:
                    start_date = s.expected_restock_date + timedelta(days=min_days)
                    end_date = s.expected_restock_date + timedelta(days=max_days)
                    expected_str = f"{start_date} ~ {end_date}"
                else:
                    expected_str = ""

                # (B) OutOfStockMapping 테이블에 upsert
                out_item, created = OutOfStockMapping.objects.update_or_create(
                    option_code=s.option_code,
                    defaults={
                        "order_product_name":  s.order_product_name,
                        "order_option_name":   s.order_option_name,
                        "store_name":          s.store_name,
                        "seller_product_name": s.seller_product_name,
                        "seller_option_name":  s.seller_option_name,
                        "expected_date":       expected_str,
                    }
                )
                logger.debug(
                    f"[send_option_mapping] OutOfStockMapping upserted: option_code={s.option_code}, "
                    f"created={created}"
                )
                updated_count += 1

            messages.success(request, f"{updated_count}건 옵션매핑(OutOfStockMapping) 전송 완료.")

            # ------------------------
            # 2) "ST_stock_update" 로직을 *같은 요청* 안에서 실행
            # ------------------------
            details_qs = OptionPlatformDetail.objects.select_related('option_mapping').all()
            if not details_qs.exists():
                messages.warning(request, "업데이트할 OptionPlatformDetail 데이터가 없습니다.")
                return redirect('out_of_stock_management')

            code_list = []
            for detail_obj in details_qs:
                if detail_obj.option_mapping and detail_obj.option_mapping.option_code:
                    code_list.append(detail_obj.option_mapping.option_code)
            code_list = list(set(code_list))  # 중복 제거

            if not code_list:
                messages.warning(request, "옵션코드가 존재하지 않아 셀러툴재고 업데이트가 불가합니다.")
                return redirect('out_of_stock_management')

            stock_map = get_inventory_by_option_codes(code_list)
            logger.debug(f"[ST_stock_update] stock_map={stock_map}")

            updated_st_count = 0
            for detail_obj in details_qs:
                if detail_obj.option_mapping:
                    code = detail_obj.option_mapping.option_code
                    old_stock = getattr(detail_obj, "seller_tool_stock", 0)
                    new_stock = stock_map.get(code, 0)

                    if new_stock != old_stock:
                        detail_obj.seller_tool_stock = new_stock
                        detail_obj.save()
                        updated_st_count += 1

            messages.success(request, f"{updated_st_count}건의 셀러툴재고가 갱신되었습니다.")

            # 마지막 리다이렉트: 품절관리 페이지
            return redirect('out_of_stock_management')
            

    # 아무것도 처리되지 않았다면(None 반환 방지)
    return redirect('delayed_shipment_list')

    
def delete_delayed_shipment(request, shipment_id):
    if request.method == 'POST':
        shipment = get_object_or_404(DelayedShipment, id=shipment_id)
        shipment.delete()
        messages.success(request, "삭제가 완료되었습니다.")
    return redirect('delayed_shipment_list')

def delayed_exchange_options_view(request):

    # 예: GET 파라미터로 option_code를 받는다고 가정
    option_code = request.GET.get('option_code')

    if not option_code:
        return render(request, 'error.html', {'message': 'option_code 파라미터가 필요합니다.'})

    exchangeable_options = get_exchangeable_options(option_code)

    return render(request, 'delayed_management/exchangeable_options.html', {
        'option_code': option_code,
        'exchangeable_options': exchangeable_options
    })


# 상태별 ETA 범위 (예시)
ETA_RANGES = {
    'purchase':  (14, 21),   # 구매된상품들: 14~21일
    'shipping':  (10, 14),   # 배송중
    'arrived':   (7, 10),    # 도착완료
    'document':  (5, 7),     # 서류작성
    'loading':   (1, 4),     # 선적중
}

def restock_list(request):
    """
    재입고/배송지연 목록을 보여주는 예시 뷰.
    - restock_date(고정) + min/max
    - expected_restock_date(동적) + min/max
    """
    shipments = DelayedShipment.objects.all().order_by('-created_at')

    for s in shipments:
        min_days, max_days = ETA_RANGES.get(s.status, (0, 0))

        # 1) 고정 안내날짜 range
        if s.restock_date:
            start1 = s.restock_date + timedelta(days=min_days)
            end1   = s.restock_date + timedelta(days=max_days)
            # 템플릿에서 {{ s.range_start }} / {{ s.range_end }} 로 접근
            s.range_start = start1
            s.range_end   = end1
        else:
            s.range_start = None
            s.range_end   = None

        # 2) 동적 예상날짜 range
        if s.expected_restock_date:
            start2 = s.expected_restock_date + timedelta(days=min_days)
            end2   = s.expected_restock_date + timedelta(days=max_days)
            s.expected_start = start2
            s.expected_end   = end2
        else:
            s.expected_start = None
            s.expected_end   = None

    return render(request, 'delayed_management/restock_management.html', {
        'shipments': shipments,
    })

def restock_update(request):
    """
    상태/ETA 조정 폼에서 POST로 수신하는 예시
    (option_code가 여러 레코드에 중복될 수 있으므로 filter(...)로 일괄 처리)
    """
    if request.method == 'POST':
        option_code = request.POST.get('option_code', '').strip()
        if not option_code:
            messages.error(request, "옵션코드가 없습니다.")
            return redirect('restock_list')

        # 기존: shipment = get_object_or_404(DelayedShipment, option_code=option_code)
        # 변경: 여러 레코드 filter
        qs = DelayedShipment.objects.filter(option_code=option_code)
        if not qs.exists():
            messages.error(request, f"해당 옵션코드({option_code})를 가진 레코드가 없습니다.")
            return redirect('restock_list')

        new_status = request.POST.get('status', '').strip()
        new_eta = request.POST.get('eta', '').strip()

        # (A) 상태 업데이트
        if new_status:
            qs.update(status=new_status)

        # (B) ETA(날짜) 업데이트
        if new_eta:
            try:
                y, m, d = new_eta.split('-')
                parsed_date = date(int(y), int(m), int(d))
            except ValueError:
                messages.error(request, "유효한 날짜 형식(YYYY-MM-DD)이 아닙니다.")
                return redirect('restock_list')

            # 만약 eta 필드가 있다면 (존재한다면)
            # qs.update(eta=parsed_date)
            # restock_date도 마찬가지로 필요 시 bulk update 가능
            #
            # 혹은 개별 로직이 필요하다면:
            for shipment in qs:
                # 예: 기존에 eta가 비어있을 때만 넣겠다
                if not shipment.eta:
                    shipment.eta = parsed_date
                shipment.save()

        updated_count = qs.count()  # 실제 몇 건이 영향을 받았는지

        messages.success(request, f"옵션코드 {option_code}의 {updated_count}건이 업데이트되었습니다.")
        return redirect('restock_list')

    # GET 등 잘못된 접근은 목록 페이지로 이동
    return redirect('restock_list')


tabs = ["구매된상품들", "배송중", "도착완료", "서류작성", "선적중"]



def map_status(raw_status):
    if raw_status == "구매된상품들":
        return "purchase"
    elif raw_status == "배송중":
        return "shipping"
    elif raw_status == "도착완료":
        return "arrived"
    elif raw_status == "서류작성":
        return "document"
    elif raw_status == "선적중":
        return "loading"
    return "nopurchase"

def update_restock_from_sheet(request):
    service_account_file = settings.SERVICE_ACCOUNT_FILE
    spreadsheet_id = "1qQfo2Pp-odUuYwKmQXNPv1phzK6Gi2JtlJYaaz3T1F0"

    client = get_gspread_client(service_account_file)
    sh = client.open_by_key(spreadsheet_id)

    tabs = ["구매된상품들", "배송중", "도착완료", "서류작성", "선적중"]
    today = date.today()
    total_updated = 0

    for tab_name in tabs:
        try:
            worksheet = sh.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            print(f"=== 시트 '{tab_name}' 없음, 건너뜁니다.")
            continue

        data = worksheet.get_all_values()
        for idx, row in enumerate(data[1:], start=2):
            # row[0]에 option_code가 있다고 가정
            if not row or len(row) < 1:
                continue

            option_code = (row[0] or "").strip()
            if not option_code:
                continue

            # 스프레드시트 탭 이름으로 상태 매핑
            status_code = map_status(tab_name)

            # ETA 계산 (min_days만 사용)
            min_days, max_days = ETA_RANGES.get(status_code, (0, 0))
            calc_date = today + timedelta(days=min_days) if min_days else None

            # ▼ 변경 후 코드: filter(...) 사용 (get(...) 대신)
            qs = DelayedShipment.objects.filter(option_code=option_code)
            if not qs.exists():
                # 해당 option_code가 없으면 스킵
                continue

            # 1) status, expected_restock_date bulk update
            qs.update(
                status=status_code,
                expected_restock_date=calc_date
            )

            # 2) restock_date는 None인 경우에만 세팅
            for ship in qs:
                if ship.restock_date is None:
                    ship.restock_date = calc_date
                    ship.save()

            total_updated += qs.count()

    messages.success(
        request,
        f"{total_updated}건 동기화 완료 (restock_date는 최초 1회만 설정, expected_restock_date는 매번 갱신)."
    )
    return redirect('restock_management')






# Solapi API 환경변수
SOLAPI_API_KEY = config('SOLAPI_API_KEY', default=None)
SOLAPI_API_SECRET = config('SOLAPI_API_SECRET', default=None)
SOLAPI_SENDER_NUMBER = config('SOLAPI_SENDER_NUMBER', default='')  # 발신번호


def send_message_list(request):
    qs = DelayedShipment.objects.filter(flow_status='sent').order_by('-created_at')
    today = date.today()
    for s in qs:
        min_days, max_days = ETA_RANGES.get(s.status, (0,0))

        # 고정 안내날짜 range
        if s.restock_date:
            s.range_start = s.restock_date + timedelta(days=min_days)
            s.range_end   = s.restock_date + timedelta(days=max_days)
        else:
            s.range_start = None
            s.range_end   = None

        # 동적 예상날짜 range
        if s.expected_restock_date:
            s.expected_start = s.expected_restock_date + timedelta(days=min_days)
            s.expected_end   = s.expected_restock_date + timedelta(days=max_days)
        else:
            s.expected_start = None
            s.expected_end   = None
    return render(request, 'delayed_management/send_message_list.html', {
        'shipments': qs
    })

def send_message_process(request):
    if request.method == 'POST':
        action = request.POST.get('action', '')
        logger.debug(f"=== DEBUG: send_message_process() action={action}")

        shipment_ids = request.POST.getlist('shipment_ids', [])
        logger.debug(f"=== DEBUG: shipment_ids={shipment_ids}")

        # (A) 선택 삭제(delete_multiple)
        if action == 'delete_multiple':
            if not shipment_ids:
                messages.error(request, "삭제할 항목이 선택되지 않았습니다.")
                return redirect('send_message_list')

            qs = DelayedShipment.objects.filter(id__in=shipment_ids)
            deleted_info = qs.delete()
            total_deleted = deleted_info[0]  # (삭제된 객체 수, { 'app.Model': count })
            return redirect('send_message_list')
        
        elif action == 'check_status':
            logger.debug("=== DEBUG: 전송상태 확인(check_status) 진입 ===")
            shipment_ids = request.POST.getlist('shipment_ids', [])
            if not shipment_ids:
                messages.error(request, "전송상태 확인할 항목이 선택되지 않았습니다.")
                return redirect('send_message_list')

            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            if not shipments.exists():
                messages.error(request, "해당 데이터가 존재하지 않습니다.")
                return redirect('send_message_list')

            group_ids = set(
                shipments.values_list('solapi_group_id', flat=True)
                .exclude(solapi_group_id__isnull=True)
                .exclude(solapi_group_id__exact='')
            )
            logger.debug(f"=== DEBUG: group_ids={group_ids}")

            if not group_ids:
                messages.warning(request, "해당 항목에 groupId가 없습니다 (미발송 상태이거나 오류).")
                return redirect('send_message_list')

            for gid in group_ids:
                if not gid:
                    continue
                try:
                    logger.debug(f"=== DEBUG: check_solapi_group_status_and_update(gid={gid}) 호출")
                    check_solapi_group_status_and_update(gid)
                except Exception as e:
                    logger.exception(f"=== DEBUG: 상태조회 groupId={gid} 에러 => {e}")

            messages.success(request, f"총 {len(group_ids)}개 groupId 상태조회 완료.")
            return redirect('send_message_list')


        # (B) 문자 발송(send_sms)
        elif action == 'resend_sms':
            logger.debug("=== DEBUG: 문자 재발송 로직(resend_sms) 진입 ===")

            # 1) 체크된 항목이 있는지 확인
            if not shipment_ids:
                messages.error(request, "재발송할 항목이 선택되지 않았습니다.")
                return redirect('send_message_list')

            # 2) DB에서 Shipment 목록 조회
            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            if not shipments.exists():
                messages.error(request, "발송할 데이터가 없습니다.")
                logger.debug("=== DEBUG: DB 조회결과 없음 ===")
                return redirect('send_message_list')

            # 3) 메시지 목록 및 로컬 실패 리스트
            messages_list = []
            local_fail_ids = []

            for s in shipments:
                # (A) 스토어명 없는 경우 → 실패 처리 후 continue
                if not s.store_name:
                    logger.debug(f"=== DEBUG: store_name 없음, shipment_id={s.id}")
                    local_fail_ids.append(s.id)
                    s.send_status = 'FAIL'
                    s.save()
                    continue

                # (B) store_name → pf_id/template_id
                channel_name = map_store_to_channel(s.store_name)
                pf_id = get_pfId_by_channel(channel_name)
                template_id = get_templateId_by_channel(channel_name)

                # (C) 발송유형, 상태 임시 설정
                if pf_id:
                    s.send_type = 'KAKAO'
                else:
                    s.send_type = 'SMS'
                s.send_status = 'SENDING'
                s.save()

                # (D) 재입고 안내날짜 계산
                min_days, max_days = ETA_RANGES.get(s.status, (0, 0))
                if s.restock_date:
                    start_d = s.restock_date + timedelta(days=min_days)
                    end_d   = s.restock_date + timedelta(days=max_days)
                    발송일자_str = f"{start_d.strftime('%Y.%m.%d')} ~ {end_d.strftime('%m.%d')}"
                else:
                    발송일자_str = "상담원문의"

                # (E) URL 치환변수
                url_thx = f"piaarlab.store/delayed/customer-action?action=wait&token={s.token}"
                url_change = f"piaarlab.store/delayed/option-change?action=change&token={s.token}"

                # (F) 알림톡/문자용 치환 변수
                variables = {
                    '#{고객명}': s.customer_name or "",
                    '#{상품명}': s.order_product_name or "",
                    '#{옵션명}': s.order_option_name or "",
                    '#{발송일자}': 발송일자_str,
                    '#{교환옵션명}': s.exchangeable_options or "",
                    '#{채널명}': s.store_name or "",
                    '#{url}': "example.com",
                    '#{url_thx}': url_thx,
                    '#{url_change}': url_change,
                }

                # (G) Solapi 메시지 오브젝트
                msg_obj = {
                    "to": s.customer_contact or "",
                    "from": SOLAPI_SENDER_NUMBER,   # 예: "023389465"
                }

                if pf_id:
                    # (알림톡) kakaoOptions
                    msg_obj["kakaoOptions"] = {
                        "pfId": pf_id,
                        "templateId": template_id,
                        "variables": variables
                    }
                else:
                    # (SMS) text
                    # 여기서 [재발송] 문구만 추가
                    msg_obj["text"] = (
                        f"[재발송]\n"
                        f"안녕하세요 {s.customer_name or ''}님,\n"
                        f"{s.order_product_name or ''} 제품이 품절되어 연락드렸습니다.\n"
                        f"구매하신 스토어로 연락주시면 상품 변경 및 취소처리를 "
                        f"빠르게 도와드릴 수 있도록 하겠습니다. 감사합니다."
                    )

                # (H) messages_list 에 (shipment, msg) 형태로 추가
                messages_list.append((s, msg_obj))

            # 4) 만약 실제 발송할 대상이 전혀 없다면(스토어명 없는 항목만 골랐거나 등)
            if not messages_list and not local_fail_ids:
                logger.debug("=== DEBUG: 재발송 대상이 전혀 없음 ===")
                messages.warning(request, "재발송 대상이 없습니다.")
                return redirect('send_message_list')

            # 5) Solapi 발송
            try:
                logger.debug("=== DEBUG: solapi_send_messages() 호출 (resend_sms) ===")
                success_list, fail_list, group_id = solapi_send_messages(messages_list)

                # (A) store_name 없는 항목 등 미발송 → fail_list 합치기
                fail_list.extend(local_fail_ids)

                # (B) DB 업데이트 (성공 / 실패)
                DelayedShipment.objects.filter(id__in=success_list).update(
                    flow_status='sent',
                    send_status='SUCCESS'
                )
                DelayedShipment.objects.filter(id__in=fail_list).update(
                    flow_status='pre_send',
                    send_status='FAIL'
                )

                messages.success(request, f"재발송 완료 (groupId={group_id})")
                logger.debug("=== DEBUG: 문자 재발송 완료 ===")

            except Exception as e:
                logger.exception("=== DEBUG: 문자 재발송 오류 ===")
                messages.error(request, f"문자 재발송 오류: {str(e)}")

            # 6) 끝나면 목록 리다이렉트
            return redirect('send_message_list')


    # 그 외(GET 등) 잘못된 요청이면 리스트 페이지로
    return redirect('send_message_list')



def solapi_send_messages(messages_list):
    """
    HTTP 200 -> success_list
    else -> fail_list
    """
    success_list = []
    fail_list = []
    group_id = None

    body = {"messages": []}
    for s, msg_obj in messages_list:
        # 이미 customFields / shipment_id 를 세팅했으므로 OK
        body["messages"].append(msg_obj)

        s.send_type = 'SMS'  # 임시
        s.send_status = 'SENDING'
        s.save()

    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec='seconds')
    salt = str(uuid.uuid4())
    signature = make_solapi_signature(now_iso, salt, SOLAPI_API_SECRET)
    auth_header = f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={now_iso}, salt={salt}, signature={signature}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_header
    }
    url = "https://api.solapi.com/messages/v4/send-many"
    res = requests.post(url, json=body, headers=headers, timeout=10)
    if res.status_code == 200:
        res_json = res.json()
        group_id = res_json.get("groupId")
        for s, _ in messages_list:
            s.send_status = 'SUCCESS'
            s.message_sent_at = timezone.now()
            s.save()
            success_list.append(s.id)
    else:
        for s, _ in messages_list:
            s.send_type = 'NONE'
            s.send_status = 'FAIL'
            s.save()
            fail_list.append(s.id)

    return success_list, fail_list, group_id


def check_solapi_group_status_and_update(group_id):
    """
    Solapi에서 최종 상태를 가져와 (알림톡 성공/문자 성공/실패) DB에 반영.
    여기서는 /messages/v4/groups/{groupId}?withMessageList=true 이용.
    """
    logger.debug("=== DEBUG: check_solapi_group_status_and_update() start ===")
    logger.debug(f"=== DEBUG: group_id={group_id}")

    # 1) /messages/v4/groups/{groupId}?withMessageList=true
    url = f"https://api.solapi.com/messages/v4/groups/{group_id}?withMessageList=true"
    logger.debug(f"=== DEBUG: groups endpoint URL => {url}")

    # 인증
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec='seconds')
    salt = str(uuid.uuid4())
    signature = make_solapi_signature(now_iso, salt, SOLAPI_API_SECRET)
    auth_header = f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={now_iso}, salt={salt}, signature={signature}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_header
    }

    res = requests.get(url, headers=headers, timeout=10)
    logger.debug(f"=== DEBUG: check_solapi_group_status code={res.status_code}, body[:500]={res.text[:500]}")
    if res.status_code != 200:
        logger.warning(f"=== DEBUG: groupId={group_id} 상태조회 실패 => {res.text}")
        return

    data = res.json()
    # messageList 안에 각 메시지별 상태가 들어 있을 수 있음
    message_list = data.get("messageList", [])
    logger.debug(f"=== DEBUG: messageList size={len(message_list)}")

    if not message_list:
        logger.debug("=== DEBUG: messageList 비어있음 => 처리 불가 (아직 SENDING 중일 가능성)")
        return

    # 2) 메시지별 처리
    for i, msg_item in enumerate(message_list):
        logger.debug(f"=== DEBUG: [#{i}] msg_item => {msg_item}")

        cf = msg_item.get("customFields", {})
        shipment_id_str = cf.get("shipment_id")
        if not shipment_id_str:
            logger.debug("=== DEBUG: shipment_id 없음 => 건너뜀")
            continue

        try:
            shipment_id = int(shipment_id_str)
            s = DelayedShipment.objects.get(id=shipment_id)
        except (ValueError, DelayedShipment.DoesNotExist):
            logger.debug(f"=== DEBUG: invalid shipment_id={shipment_id_str}")
            continue

        # 알림톡 성공 여부
        # Solapi 문서에 따라 "statusCode"가 "2000"이면 성공
        main_code = msg_item.get("statusCode")  # 알림톡 상태
        # 대체발송 문자
        failover = msg_item.get("failover", {})
        failover_code = failover.get("statusCode")  # "2000"이면 문자 성공

        logger.debug(f"=== DEBUG: shipment<{s.id}> main_code={main_code}, failover_code={failover_code}")

        # 실제 로직
        if main_code == "2000":
            # 알림톡 성공
            s.send_type = 'KAKAO'
            s.send_status = 'SUCCESS'
            logger.debug(f"   => 알림톡 성공 처리 (shipment_id={s.id})")
        elif failover_code == "2000":
            # 알림톡 실패, 문자 성공
            s.send_type = 'SMS'
            s.send_status = 'SUCCESS'
            logger.debug(f"   => 문자 성공 처리 (shipment_id={s.id})")
        else:
            # 둘 다 실패
            s.send_type = 'SMS'
            s.send_status = 'FAIL'
            logger.debug(f"   => 둘 다 실패 처리 (shipment_id={s.id})")

        s.save()

    logger.debug("=== DEBUG: check_solapi_group_status_and_update() end ===")


@csrf_exempt
def solapi_webhook_message(request):
    """
    Solapi "메시지 리포트" 웹훅
    예: [ { "messageId":"...", "type":"ATA", "statusCode":"4000", "customFields":{"shipment_id":"298"}, ... }, ... ]
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        body_str = request.body.decode('utf-8')
        data_list = json.loads(body_str)  # [ {...}, {...} ]
    except Exception as e:
        logger.debug(f"=== WEBHOOK ERROR: invalid JSON => {str(e)}")
        return JsonResponse({"error": f"invalid json: {str(e)}"}, status=400)

    # data_list 루프
    for item in data_list:
        # 1) 로그 출력
        logger.debug("=== WEBHOOK ITEM START ===")
        logger.debug(f"messageId={item.get('messageId')}")
        logger.debug(f"groupId={item.get('groupId')}")
        logger.debug(f"type={item.get('type')}  statusCode={item.get('statusCode')}")
        logger.debug(f"customFields={item.get('customFields', {})}")
        logger.debug("=== WEBHOOK ITEM END ===")

        # 2) 필요한 필드 파싱
        message_id  = item.get("messageId")
        group_id    = item.get("groupId")
        type_       = item.get("type")         # "ATA" or "LMS" etc.
        status_code = item.get("statusCode")   # "4000" 등
        custom_fields = item.get("customFields", {})

        # 3) DB 식별
        shipment_id_str = custom_fields.get("shipment_id")
        if not shipment_id_str:
            logger.debug("No shipment_id => skip this item")
            continue

        try:
            shipment_id = int(shipment_id_str)
            s = DelayedShipment.objects.get(id=shipment_id)
        except (ValueError, DelayedShipment.DoesNotExist):
            logger.debug(f"Invalid or not-found shipment_id={shipment_id_str}")
            continue

        # 4) 분기 로직
        if type_ == "ATA" and status_code == "4000":
            # 알림톡(ATA) 성공
            s.send_type = "KAKAO"
            s.send_status = "SUCCESS"
            logger.debug(f"shipment<{s.id}> => 알림톡 SUCCESS")
        elif type_ == "LMS" and status_code == "4000":
            # 문자(LMS) 성공
            s.send_type = "SMS"
            s.send_status = "SUCCESS"
            logger.debug(f"shipment<{s.id}> => 문자(LMS) SUCCESS")
        else:
            # 나머지 -> 발송 실패
            s.send_type = "NONE"
            s.send_status = "FAIL"
            logger.debug(f"shipment<{s.id}> => FAIL (type={type_}, code={status_code})")

        s.save()

    # (5) 반드시 200 응답
    return JsonResponse({"message":"ok"}, status=200)

##########################################
# 2) 그룹 단위로 카톡을 보내는 예시 함수
##########################################
def send_kakao_for_group(group_id):
    """
    DelayedShipmentGroup 하나의 id를 받아,
    그 그룹 내에 포함된 DelayedShipment 여러 개를 한꺼번에 안내.
    """
    group = get_object_or_404(DelayedShipmentGroup, id=group_id)

    # 만약 group.token 이 없으면 새로 발행
    if not group.token:
        group.token = str(uuid.uuid4())
        group.save()

    # 그룹 대표 연락처
    contact = group.contact

    # 그룹에 속한 주문
    shipments = group.shipments.all()
    # 실제론 여러 주문에 대해 안내문을 만들거나, 첫 번째 주문만 참조할 수도 있음
    # 여기서는 첫 Shipment만 예시
    first_s = shipments.first()

    if not first_s:
        raise ValueError("이 그룹에는 DelayedShipment가 하나도 없습니다.")

    # store_name(혹은 brand)에 따라 pfId, templateId 매핑
    store_name = first_s.store_name or "기본값"
    pf_id = get_pfId_by_channel(store_name)        # 프로젝트에 맞게 구현
    template_id = get_templateId_by_channel(store_name)

    # URL: 그룹 단위로 “기다리기 / 옵션변경”을 처리할 엔드포인트
    # 예: /delayed/customer-group-action?token=...
    domain = getattr(settings, 'MY_SERVER_DOMAIN', 'https://34.64.123.206.com',"https://piaarlab.store/")
    confirm_url = f"{domain}/delayed/customer-group-action?token={group.token}"

    # 치환변수 구성
    # 만약 여러 상품명을 한꺼번에 보여주려면
    # product_summary = ", ".join([s.order_product_name for s in shipments])
    product_summary = first_s.order_product_name or "(상품명)"

    variables = {
        "#{url}": confirm_url,
        "#{상품명}": product_summary,
        "#{고객명}": first_s.customer_name or "고객님"
    }

    msg = {
        "to": contact,
        "from": getattr(settings, 'SOLAPI_SENDER_NUMBER', ''),  # 발신번호
        "kakaoOptions": {
            "pfId": pf_id,
            "templateId": template_id,
            "variables": variables
        }
    }

    # 전송
    result = solapi_send_messages([msg])  # 여러 건이면 messages 배열
    # 필요시 result를 반환 / DB 저장 처리
    return result


def make_solapi_signature(now_iso, salt, secret_key):
    # HMAC-SHA256(now_iso+salt, secret_key)
    data = (now_iso + salt).encode('utf-8')
    secret = secret_key.encode('utf-8')
    sig = hmac.new(secret, data, hashlib.sha256).hexdigest()
    return sig

def map_store_to_channel(store_name: str) -> str:
    """
    store_name → channel_name
    예) "니뜰리히", "수비다", "노는 개 최고양", "아르빙" 등
    """

    return store_name or ""

def get_pfId_by_channel(channel_name):
    """
    채널명 → pfId
    """
    pf_map = {
        "니뜰리히": "KA01PF241004055851440a91cCwGs47a",
        "수비다": "KA01PF241016104213982rcJgXgeHWd8",
        "수비다 SUBIDA": "KA01PF241016104213982rcJgXgeHWd8",
        "노는 개 최고양": "KA01PF241016104250071z8FktOivA0r",
        "노는개최고양": "KA01PF241016104250071z8FktOivA0r",
        "아르빙": "KA01PF241016104450781C2ssOn2lCCM",
    }
    return pf_map.get(channel_name, "")

def get_templateId_by_channel(channel_name):
    """
    채널명 → templateId
    """
    tmpl_map = {
        "니뜰리히": "KA01TP241230063811612F7QtAXfIYxu",
        "수비다": "KA01TP241230063811612F7QtAXfIYxu",
        "수비다 SUBIDA": "KA01TP241230063811612F7QtAXfIYxu",
        "노는 개 최고양": "KA01TP241230063811612F7QtAXfIYxu",
        "노는개최고양": "KA01TP241230063811612F7QtAXfIYxu",
        "아르빙": "KA01TP241230063811612F7QtAXfIYxu",
    }
    return tmpl_map.get(channel_name, "")

def confirm_token_view(request):
    token = request.GET.get('token', '')
    if not token:
        return HttpResponse("잘못된 접근", status=400)

    try:
        shipment = DelayedShipment.objects.get(token=token)
        shipment.confirmed = True
        shipment.save()
        return HttpResponse("확인 처리되었습니다. 감사합니다.")
    except DelayedShipment.DoesNotExist:
        return HttpResponse("유효하지 않은 토큰", status=404)
    

def customer_action_view(request):
    action = request.GET.get('action', '')
    token = request.GET.get('token', '')
    logger.debug(f"=== DEBUG: action={action}, token={token}")

    if not token:
        return HttpResponse("유효하지 않은 요청: token 없음", status=400)

    shipment = DelayedShipment.objects.filter(token=token).first()
    logger.debug(f"=== DEBUG: found shipment={shipment} for token={token}")
    if not shipment:
        return HttpResponse("유효하지 않은 토큰", status=404)

    # 이미 waiting/changed_option 이 있다면 더 이상 변경 불가
    if shipment.waiting or shipment.changed_option:
        logger.debug(f"=== DEBUG: shipment already waiting={shipment.waiting} or changed_option={shipment.changed_option}")
        return HttpResponse("이미 처리된 내역이 존재합니다. 더 이상 변경할 수 없습니다.")

    if action == 'wait':
        shipment.waiting = True
        shipment.confirmed = True
        # 발송흐름 상태도 '확인완료'로
        logger.debug(f"=== DEBUG: Before: flow_status={shipment.flow_status}, waiting={shipment.waiting}")
        shipment.flow_status = 'confirmed'
        shipment.save()
        return redirect(f'/delayed/thank-you/?token={token}')

    elif action == 'change':
        # TODO: flow_status='confirmed' 는 옵션변경 후 최종 저장(옵션변경 완료 시점)에 세팅
        return redirect(f"/delayed/option-change/?token={token}")

    else:
        return HttpResponse("잘못된 action", status=400)

    
    
def thank_you_view(request):
    
    """
    "기다리기" 버튼을 클릭한 뒤 띄울 페이지.
    간단한 감사 메시지를 렌더링 + 제품도착예상 날짜 표시.
    """
    token = request.GET.get('token', '')
    logger.debug("thank_you_view() token = %s", token)
    shipments = DelayedShipment.objects.filter(token=token)
    if not shipments.exists():
        return HttpResponse("유효하지 않은 토큰", status=404)

    # 각 Shipment마다 예상날짜 계산
    for s in shipments:
        min_days, max_days = ETA_RANGES.get(s.status, (0, 0))
        if s.expected_restock_date:
            s.expected_start = s.expected_restock_date + timedelta(days=min_days)
            s.expected_end   = s.expected_restock_date + timedelta(days=max_days)
        else:
            s.expected_start = None
            s.expected_end   = None

    return render(request, 'delayed_management/thank_you.html', {
        'shipments': shipments,
    }) 

def option_change_view(request):
    token = request.GET.get('token', '')
    logger.debug("option_change_view() token = %s", token)
    shipments = DelayedShipment.objects.filter(token=token)
    if not shipments.exists():
        return HttpResponse("유효하지 않은 토큰", status=404)

    # 1) ETA_RANGES 등 상태별 날짜 계산
    for s in shipments:
        min_days, max_days = ETA_RANGES.get(s.status, (0, 0))

        # (1) 고정 안내날짜
        if s.restock_date:
            s.range_start = s.restock_date + timedelta(days=min_days)
            s.range_end   = s.restock_date + timedelta(days=max_days)
        else:
            s.range_start = None
            s.range_end   = None

        # (2) 동적 예상날짜
        if s.expected_restock_date:
            s.expected_start = s.expected_restock_date + timedelta(days=min_days)
            s.expected_end   = s.expected_restock_date + timedelta(days=max_days)
        else:
            s.expected_start = None
            s.expected_end   = None

    shipments_data = []
    for s in shipments:
        # (A) DB에 있는 '교환옵션' 문자열 → splitted
        #    예: "애쉬그레이(R),샌드카키(L),오트밀베이지(R)"
        if s.exchangeable_options:
            splitted = [opt.strip() for opt in s.exchangeable_options.split(',') if opt.strip()]
        else:
            splitted = []

        # (B) 실제 API 통해 **optionCode** 포함한 전체 dict list 가져오기
        try:
            needed_qty = int(s.quantity or 1)
        except ValueError:
            needed_qty = 1

        # 예: [{optionName:'애쉬그레이(R)', optionCode:'4qom1...', stock:2}, ...] 
        full_list = get_exchangeable_options(s.option_code, needed_qty)

        # (C) splitted(=DB 저장된 옵션명 목록)와 일치하는 옵션만 선별
        #     → 최종 real_options
        real_options = []
        for opt_info in full_list:  
            # opt_info 예: {"optionName":"애쉬그레이(R)","optionCode":"..."}
            if opt_info["optionName"] in splitted:
                real_options.append(opt_info)

        # (주의) 만약 splitted에 없는 **재고가능 옵션**도 다 보여주길 원한다면,
        #       그냥 full_list 전체를 사용해도 좋습니다.
        #       여기서는 "DB에 저장된 목록"만 제한적으로 뿌린다고 가정.

        shipments_data.append({
            "shipment": s,
            "exchangeable_options": real_options,  # => 템플릿에선 opt.optionName / opt.optionCode 사용
        })

    return render(request, 'delayed_management/change_option.html', {
        "shipments_data": shipments_data,
        "token": token,
    })


def option_change_process(request):
    if request.method != 'POST':
        return HttpResponse("잘못된 접근입니다.", status=405)

    token = request.POST.get('token', '')
    shipments = DelayedShipment.objects.filter(token=token)
    if not shipments.exists():
        return HttpResponse("유효하지 않은 토큰", status=404)

    # 이미 waiting=True or changed_option 이 있으면 수정 불가
    any_already = shipments.filter(Q(waiting=True) | ~Q(changed_option='')).exists()
    logger.debug(f"=== DEBUG: [option_change_process] token={token}")
    logger.debug(f"=== DEBUG: shipments.count={shipments.count()}")
    logger.debug(f"=== DEBUG: any_already={any_already}")
    if any_already:
        return HttpResponse("이미 처리된 내역이 존재합니다.", status=400)

    for s in shipments:
        new_opt_key  = f"new_option_for_{s.id}"
        new_code_key = f"new_option_code_for_{s.id}"
        new_qty_key  = f"new_qty_for_{s.id}"  # 수량 변경 고려 시

        new_option     = request.POST.get(new_opt_key, '')
        new_option_code= request.POST.get(new_code_key, '')
        new_qty_str    = request.POST.get(new_qty_key, '1')

        try:
            new_qty = int(new_qty_str)
        except ValueError:
            new_qty = 1

        logger.debug(f"=== DEBUG: shipment.id={s.id}, new_option={new_option}, new_option_code={new_option_code}, new_qty_str={new_qty_str}")

        # 선택된 옵션이 없거나 "옵션을 선택하세요" 그대로면 처리
        stripped_option = new_option.strip()
        if not stripped_option:
            logger.debug("=== DEBUG: 선택된 옵션이 없거나 '옵션을 선택하세요' 그대로임")
            new_option = "변경 가능한 옵션이 없습니다. 상담원에게 문의해주세요."
            new_option_code = ""

        logger.debug(f"=== DEBUG: [SAVE] shipment.id={s.id} => changed_option={new_option}, changed_option_code={new_option_code}")

        s.changed_option = new_option
        s.changed_option_code = new_option_code
        s.quantity = new_qty
        s.confirmed = True
        s.waiting   = False
        s.flow_status = 'confirmed'
        s.save()

    logger.debug("=== DEBUG: 모든 shipment에 대해 옵션변경 완료 → option_change_done redirect")
    return redirect('option_change_done')





def option_change_done(request):
    return render(request, 'delayed_management/option_change_done.html')

def customer_group_action_view(request):
    token = request.GET.get('token', '')
    if not token:
        return HttpResponse("token이 없습니다.", status=400)

    group = DelayedShipmentGroup.objects.filter(token=token).first()
    if not group:
        return HttpResponse("유효하지 않은 token.", status=404)

    # group 내 모든 Shipment
    shipments = group.shipments.all()
    # 템플릿에서 "옵션별로 기다리기 or 변경"을 표시하도록
    return render(request, 'delayed_management/customer_group_action.html', {
        'group': group,
        'shipments': shipments
    })





def process_confirmed_shipments(request):
    """
    confirmed_list 템플릿에서 POST로 전달된 shipment_ids 에 대해
    - action = "complete_process" → 출고완료(flow_status='shipped' 등)
    - action = "delete_multiple"  → 선택 삭제
    """
    if request.method == 'POST':
        action = request.POST.get('action', '')
        shipment_ids = request.POST.getlist('shipment_ids', [])

        if not shipment_ids:
            messages.warning(request, "선택된 항목이 없습니다.")
            return redirect('confirmed_list')

        qs = DelayedShipment.objects.filter(id__in=shipment_ids)

        if action == 'complete_process':
            # 출고완료 버튼을 눌렀을 때
            count = qs.update(flow_status='shipped')  # 필요에 따라 send_status 등 다른 필드도 업데이트
            messages.success(request, f"{count}건 출고완료로 변경했습니다.")
            return redirect('confirmed_list')

        elif action == 'delete_multiple':
            # 선택 삭제 버튼을 눌렀을 때
            deleted_info = qs.delete()
            total_deleted = deleted_info[0]  # (삭제된 객체 수, { 'app.Model': count })
            return redirect('confirmed_list')

        elif action == 'revert_waiting':
            """
            '기다리기로 변경' 로직:
            - 기존에 changed_option (옵션변경)이나 confirmed=True 였던 것을 다시 'waiting=True'로 돌림
            - changed_option=''(초기화), changed_option_code=''(초기화)
            - confirmed=False (다시 미확인 상태)
            - waiting=True
            - flow_status=... (선택: pre_send? confirmed? 여기서 '기다리는 중'을 어떤 flow_status로 둘지 결정)
            """
            count = 0
            for s in qs:
                s.changed_option = ""
                s.changed_option_code = ""
                s.waiting = True
                s.confirmed = True
                s.flow_status = 'confirmed'  # 또는 'pre_send' 등, 원하는 흐름상태
                s.save()
                count += 1

            messages.success(request, f"{count}건 기다리기로 변경했습니다.")
            return redirect('confirmed_list')
        
        else:
            # 정의되지 않은 action일 경우
            messages.error(request, "알 수 없는 요청입니다.")
            return redirect('confirmed_list')

    # GET 혹은 다른 메소드로 접근 시 목록 페이지로
    return redirect('confirmed_list')




def shipped_list_view(request):
    """
    flow_status='shipped' 인 데이터들만 보여주는 출고완료 페이지
    """
    shipments = DelayedShipment.objects.filter(flow_status='shipped').order_by('-created_at')
    return render(request, 'delayed_management/shipped_list.html', {'shipments': shipments})


def process_shipped_shipments(request):
    """
    '출고완료 목록' 템플릿에서 POST로 전달된 shipment_ids에 대해
    - action = "delete_multiple"      → 선택 삭제
    - action = "revert_to_confirmed" → 확인완료로 되돌리기(flow_status='confirmed')
    """
    if request.method == 'POST':
        action = request.POST.get('action', '')
        shipment_ids = request.POST.getlist('shipment_ids', [])

        if not shipment_ids:
            messages.warning(request, "선택된 항목이 없습니다.")
            return redirect('shipped_list')  # 실제 템플릿 이름/URL에 맞게 변경

        qs = DelayedShipment.objects.filter(id__in=shipment_ids)

        if action == 'delete_multiple':
            # 예: 실제로는 delete가 아니라 is_deleted 처리 등으로 구현할 수도 있음
            count = qs.delete()[0]  # delete()는 (삭제개수, {테이블정보}) 형태로 반환
            messages.success(request, f"{count}건을 삭제했습니다.")
            return redirect('shipped_list')

        elif action == 'revert_to_confirmed':
            # 확인완료로 되돌리기
            count = qs.update(flow_status='confirmed')
            messages.success(request, f"{count}건을 확인완료 상태로 되돌렸습니다.")
            return redirect('shipped_list')

    # GET 등 다른 요청이면 그냥 목록 페이지로
    return redirect('shipped_list')

def confirmed_list(request):
    """
    flow_status='confirmed' 인 레코드를 기본으로 가져오되,
    GET 파라미터 filter에 따라 waiting / changed_option 필터
    """
    qs = DelayedShipment.objects.filter(flow_status='confirmed')

    filter_val = request.GET.get('filter', 'all')  # 디폴트 'all'
    if filter_val == 'waiting':
        qs = qs.filter(waiting=True)
    elif filter_val == 'changed':
        qs = qs.filter(~Q(changed_option=''))

    shipments = qs.order_by('-created_at')

    # ▼ 안내날짜(range_start, range_end), 예상날짜(expected_start, expected_end) 계산
    for s in shipments:
        # status에 따른 min_days, max_days
        min_days, max_days = ETA_RANGES.get(s.status, (0, 0))

        # (1) 안내날짜(고정) range
        if s.restock_date:
            s.range_start = s.restock_date + timedelta(days=min_days)
            s.range_end   = s.restock_date + timedelta(days=max_days)
        else:
            s.range_start = None
            s.range_end   = None

        # (2) 예상날짜(매번 갱신) range
        if s.expected_restock_date:
            s.expected_start = s.expected_restock_date + timedelta(days=min_days)
            s.expected_end   = s.expected_restock_date + timedelta(days=max_days)
        else:
            s.expected_start = None
            s.expected_end   = None

        # (3) changed_option(문자열) 파싱 (한 개만 있는 상황 가정)
        #     예: "애쉬그레이(R)|4qom1cc59a2c2f3e3i"
        #          또는 "애쉬그레이(R)" (옵션코드 없는 경우)
        parsed_option = {
            "option_name": "",
            "option_code": ""
        }
        if s.changed_option:
            # 만약 실제로 ','가 들어있다면(여러 개로 구분) → 
            # "한 개만"이라는 전제하에 제일 앞의 토큰만 처리 or 그대로 “,”가 없다고 가정
            tk = s.changed_option.strip()

            if '|' in tk:
                nm, cd = tk.split('|', 1)
                nm = nm.strip()
                cd = cd.strip()
                parsed_option["option_name"] = nm
                parsed_option["option_code"] = cd
            else:
                # 옵션코드 없는 경우
                parsed_option["option_name"] = tk

        # 파싱 결과를 모델 인스턴스에 임시로 넣어두면, 템플릿에서 s.changed_option_parsed 로 접근 가능
        s.changed_option_parsed = parsed_option

    return render(request, 'delayed_management/confirmed_list.html', {
        'shipments': shipments,
        'filter_val': filter_val,  # 템플릿에서 현재 필터값 체크용
    })


def get_exchange_options_api(request, shipment_id):
    """
    GET /delayed/api/exchange-options/<shipment_id>/
      → { status: "success", options: [...] }
    """
    try:
        ship = DelayedShipment.objects.get(id=shipment_id)
    except DelayedShipment.DoesNotExist:
        return JsonResponse({"status":"error","message":"Shipment not found"}, status=404)

    if not ship.exchangeable_options:
        return JsonResponse({"status":"success","options":[]})
    arr = [x.strip() for x in ship.exchangeable_options.split(',') if x.strip()]
    return JsonResponse({"status":"success","options": arr})


def get_seller_tool_options_api(request, shipment_id):
    """
    GET /delayed/api/sellertool-options/<shipment_id>/
      → {
          "status":"success",
          "allOptions":[
             {"optionName":"애쉬그레이(R)", "optionCode":"4qom1cc59a2c2f3e3i", "stock":2},
             ...
          ],
          "current":["애쉬그레이(R)", "샌드카키(L)", ...]
        }
    """
    try:
        ship = DelayedShipment.objects.get(id=shipment_id)
    except DelayedShipment.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Shipment not found"}, status=404)

    # (A) DB에 저장된 교환옵션 → 리스트
    if ship.exchangeable_options:
        current_list = [x.strip() for x in ship.exchangeable_options.split(',') if x.strip()]
    else:
        current_list = []

    # (B) 기존 API Clients
    info = get_option_info_by_code(ship.option_code)
    if not info or not info.get('productName'):
        return JsonResponse({"status": "error", "message": "상품 정보가 없습니다."}, status=400)

    product_name = info['productName']

    # (C) 동일 상품의 모든 옵션 조회
    codes = get_all_options_by_product_name(product_name)
    inventory_map = get_inventory_by_option_codes(codes)  # { code: stockUnit, ...}
    detail_map = get_options_detail_by_codes(codes)       # { code: {optionName, salesPrice, ...}, ...}

    all_options = []
    base_sales_price = info['salesPrice']

    # (D) 전체 옵션 나열
    for code in codes:
        det = detail_map.get(code)
        if not det:
            continue
        stock = inventory_map.get(code, 0)
        # (선택) 만약 "판매가 동일 & 재고 >= 0" 조건만 표시 etc.
        if det['salesPrice'] == base_sales_price:
            all_options.append({
                "optionName": det['optionName'],
                "optionCode": code,
                "stock": stock
            })

    return JsonResponse({
        "status": "success",
        "allOptions": all_options,   # [{optionName, optionCode, stock}, ...]
        "current": current_list      # ["애쉬그레이(R)", "샌드카키(L)", ... ]
    })

@csrf_exempt
def add_exchange_option_api(request, shipment_id):
    """
    POST /delayed/exchange-options/<shipment_id>/add/
    FormData: option_code, option_name
    """
    if request.method != 'POST':
        return JsonResponse({"status":"error","message":"POST only"}, status=405)

    try:
        ship = DelayedShipment.objects.get(id=shipment_id)
    except DelayedShipment.DoesNotExist:
        return JsonResponse({"status":"error","message":"Shipment not found"}, status=404)

    opt_code = request.POST.get('option_code','').strip()
    opt_name = request.POST.get('option_name','').strip()
    if not opt_code or not opt_name:
        return JsonResponse({"status":"error","message":"option_code/option_name required"}, status=400)

    # 추가
    old_str = ship.exchangeable_options or ""
    arr = [x.strip() for x in old_str.split(',') if x.strip()]
    if opt_name in arr:
        return JsonResponse({"status":"error","message":"이미 존재하는 옵션명입니다."}, status=400)

    arr.append(opt_name)
    ship.exchangeable_options = ",".join(arr)
    ship.save()
    return JsonResponse({"status":"success"})

@csrf_exempt
def remove_exchange_option_api(request, shipment_id):
    """
    POST /delayed/exchange-options/<shipment_id>/remove/
      FormData: option_name
    """
    if request.method != 'POST':
        return JsonResponse({"status":"error","message":"POST only"}, status=405)

    try:
        ship = DelayedShipment.objects.get(id=shipment_id)
    except DelayedShipment.DoesNotExist:
        return JsonResponse({"status":"error","message":"Shipment not found"}, status=404)

    opt_name = request.POST.get('option_name','').strip()
    if not opt_name:
        return JsonResponse({"status":"error","message":"option_name required"}, status=400)

    if not ship.exchangeable_options:
        return JsonResponse({"status":"error","message":"no exchangeable_options"}, status=400)

    arr = [x.strip() for x in ship.exchangeable_options.split(',') if x.strip()]
    if opt_name not in arr:
        return JsonResponse({"status":"error","message":"해당 옵션이 없습니다."}, status=400)

    arr.remove(opt_name)
    ship.exchangeable_options = ",".join(arr)
    ship.save()

    return JsonResponse({"status":"success"})



def save_seller_tool_options_api(request, shipment_id):
    """
    POST /delayed/api/save-sellertool-options/<shipment_id>/
      FormData: selected_options_json = '["빨강_M", "파랑_L"]'
    """
    from django.http import JsonResponse
    from django.shortcuts import get_object_or_404
    import json
    from .models import DelayedShipment

    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)

    # DelayedShipment 조회
    shipment = get_object_or_404(DelayedShipment, id=shipment_id)

    # 1) JSON 파싱
    selected_options_json = request.POST.get('selected_options_json', '[]')
    try:
        selected_options = json.loads(selected_options_json)  # ex) ["빨강_M","파랑_L"]
    except:
        return JsonResponse({"status": "error", "message": "JSON parsing error"}, status=400)

    # 2) DB에 저장할 문자열
    new_opts_str = ', '.join(selected_options)
    shipment.exchangeable_options = new_opts_str
    shipment.save()

    return JsonResponse({"status": "success"})

def upload_platform_mapping(request):
    """
    1. 엑셀 파일 파싱
    2. 각 행에 대해 ExternalPlatformMapping 저장
    """
    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            # 에러 처리
            ...
        
        # 1) 엑셀 파싱 로직
        #    예: pandas, openpyxl, etc.
        df = pd.read_excel(file)
        
        # 2) 각 행을 돌면서 DB 저장
        for idx, row in df.iterrows():
            option_code = row.get('option_code', '')
            platform_name = row.get('platform_name', '')
            product_id = row.get('platform_product_id', '')
            option_id = row.get('platform_option_id', '')

            # create or update
            obj, created = ExternalPlatformMapping.objects.update_or_create(
                option_code=option_code,
                platform_name=platform_name,
                defaults={
                    'platform_product_id': product_id,
                    'platform_option_id': option_id
                }
            )
        # 업로드 완료 후 리다이렉트 or 메시지
        return redirect('out_of_stock_management')  # 품절관리 페이지로 이동
    
    return render(request, 'upload_platform_mapping.html') 




from django.shortcuts import render
from django.core.paginator import Paginator
from .models import (
    OutOfStockMapping,
    OptionMapping,
)

def out_of_stock_management_view(request):
    filter_val = request.GET.get('filter', 'all').strip()
    search_query = request.GET.get('search_query', '').strip()

    outofstock_qs = OutOfStockMapping.objects.order_by('-updated_at')
    combined_rows = []

    for out_of_stock in outofstock_qs:
        # (A) Mapping 찾기
        om = OptionMapping.objects.filter(option_code=out_of_stock.option_code).first()
        if not om:
            # (B) "매핑 없음" → 미매칭 (OutOfStockMapping만 존재, detail 없음)
            combined_rows.append({
                "row_type": "outofstock",
                "row_id":   out_of_stock.id,   # OutOfStockMapping pk
                "option_code": out_of_stock.option_code,
                "store_name":  out_of_stock.store_name,
                "seller_product_name": out_of_stock.seller_product_name,
                "seller_option_name":  out_of_stock.seller_option_name,
                "order_product_name":  out_of_stock.order_product_name,
                "order_option_name":   out_of_stock.order_option_name,
                "expected_date":       out_of_stock.expected_date,
                "updated_at":          out_of_stock.updated_at,
                "is_mapped":           False,
                "platform_name":       "(미매칭)",
                "representative_image": None,
                "platform_option_id":  None,
                "stock":               None,
                "seller_tool_stock":   None,
            })
        else:
            details = om.platform_details.all()
            if not details:
                # (C1) "매핑은 있지만 detail 없음" → 미매칭
                combined_rows.append({
                    "row_type": "outofstock",
                    "row_id":   out_of_stock.id,  # OutOfStockMapping pk
                    "option_code": om.option_code,
                    "store_name":  out_of_stock.store_name,
                    "seller_product_name": out_of_stock.seller_product_name,
                    "seller_option_name":  out_of_stock.seller_option_name,
                    "order_product_name":  out_of_stock.order_product_name,
                    "order_option_name":   out_of_stock.order_option_name,
                    "expected_date":       out_of_stock.expected_date,
                    "updated_at":          out_of_stock.updated_at,
                    "is_mapped":           False,
                    "platform_name":       "(미매칭)",
                    "representative_image": None,
                    "platform_option_id":  None,
                    "stock":               None,
                    "seller_tool_stock":   None,
                })
            else:
                # (C2) detail 여러 개
                for d in details:
                    combined_rows.append({
                        "row_type": "detail",
                        "row_id":   d.id,  # OptionPlatformDetail pk
                        "option_code": om.option_code,
                        "store_name":  out_of_stock.store_name,
                        "seller_product_name": out_of_stock.seller_product_name,
                        "seller_option_name":  out_of_stock.seller_option_name,
                        "order_product_name":  (d.order_product_name or
                                                out_of_stock.order_product_name),
                        "order_option_name":   (d.order_option_name or
                                                out_of_stock.order_option_name),
                        "expected_date":       out_of_stock.expected_date,
                        "updated_at":          out_of_stock.updated_at,

                        "is_mapped":         True,
                        "platform_name":     d.platform_name,
                        "representative_image": d.representative_image,
                        "platform_option_id":  d.platform_option_id,
                        "stock":             d.stock,
                        "seller_tool_stock": d.seller_tool_stock,
                    })

    # 필터 (outofstock/instock/all)
    filtered_rows = []
    if filter_val == "outofstock":
        for row in combined_rows:
            if row["stock"] == 0 or row["stock"] is None:
                filtered_rows.append(row)
    elif filter_val == "instock":
        for row in combined_rows:
            if row["stock"] is not None and row["stock"] > 0:
                filtered_rows.append(row)
    else:
        filtered_rows = combined_rows

    # 검색
    if search_query:
        tmp_results = []
        lower_q = search_query.lower()
        for row in filtered_rows:
            p_name  = (row["platform_name"] or "").lower()
            s_name  = (row["seller_product_name"] or "").lower()
            optcode = (row["option_code"] or "").lower()
            if (lower_q in p_name) or (lower_q in s_name) or (lower_q in optcode):
                tmp_results.append(row)
        filtered_rows = tmp_results

    # 페이지네이션
    paginator = Paginator(filtered_rows, 100)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    page_range_custom = page_obj.paginator.get_elided_page_range(
        page_obj.number, on_each_side=2, on_ends=1
    )

    context = {
        "details": page_obj.object_list,
        "page_obj": page_obj,
        "page_range_custom": page_range_custom,
        "filter_val": filter_val,
        "search_query": search_query,
    }
    return render(request, "delayed_management/out_of_stock_management.html", context)





def match_option_ids_view(request):
    """
    1) OutOfStockMapping 테이블에서 option_code 전부 가져옴
    2) 각 option_code로 ExternalProductOption(s) 조회 (seller_manager_code = option_code)
    3) OptionMapping도 조회/생성
    4) OptionPlatformDetail에 option_id 매핑
       - platform_name = (ext_opt.store_name) 로 설정
    5) 완료 후 품절관리 화면으로 redirect
    """
    from django.shortcuts import redirect
    from django.contrib import messages

    from .models import (
        OutOfStockMapping,
        ExternalProductOption,
        OptionMapping,
        OptionPlatformDetail
    )

    outofstock_list = OutOfStockMapping.objects.all()

    for item in outofstock_list:
        code = (item.option_code or "").strip()
        if not code:
            continue

        # (A) ExternalProductOption 중 seller_manager_code=code 인 옵션들 조회
        ext_options = ExternalProductOption.objects.filter(
            seller_manager_code=code
        )
        if not ext_options.exists():
            # 매칭할 ExternalProductOption이 없으면 스킵
            continue

        # (B) OptionMapping(우리 내부 매핑) 찾거나 생성
        mapping_obj, _ = OptionMapping.objects.get_or_create(
            option_code=code,
            defaults={
                "order_product_name":  item.order_product_name,
                "order_option_name":   item.order_option_name,
                "store_name":          item.store_name,
                "seller_product_name": item.seller_product_name,
                "seller_option_name":  item.seller_option_name,
            }
        )

        # (C) ext_options 를 돌면서, OptionPlatformDetail에 매핑
        for ext_opt in ext_options:
            # (C1) 어떤 platform_name(=스토어명)을 넣을지 결정
            #     여기서는 ExternalProductOption.store_name 우선 사용
            store_name_value = (ext_opt.store_name or "").strip()
            if not store_name_value:
                # 만약 ext_opt.store_name이 비어 있다면,
                # OutOfStockMapping.item.store_name 을 쓸 수도 있음.
                store_name_value = (item.store_name or "").strip() or "" 
                # ↑ 위 fallback "NAVER"는 예시, 
                #   "기타", "(미지정)" 등으로 바꿀 수도 있음.

            # (C2) OptionPlatformDetail upsert
            platform_opt_id = ext_opt.option_id or ""
            opd, created = OptionPlatformDetail.objects.update_or_create(
                option_mapping=mapping_obj,
                platform_name=store_name_value,   # ★ 여기서 NAVER 대신 store_name_value!
                platform_option_id=platform_opt_id,
                defaults={
                    "stock":               ext_opt.stock_quantity,
                    "price":               ext_opt.price,
                    "seller_manager_code": code,
                    "representative_image": (
                        ext_opt.product.representative_image
                        if ext_opt.product else ""
                    ),
                    "origin_product_no": (
                        str(ext_opt.product.origin_product_no)
                        if ext_opt.product else ""
                    ),
                }
            )
            # created == True면 새로 생성, False면 업데이트

    messages.success(request, "전체 Option ID 매칭 작업이 완료되었습니다.")
    return redirect('out_of_stock_management')

def out_of_stock_delete_all_view(request):
    """
    '전체 삭제' 버튼 클릭 시 동작:
    1) OutOfStockMapping 테이블 데이터 전부 삭제
    2) 필요하다면 OptionPlatformDetail 등 다른 테이블도 함께 삭제
    3) 삭제 후 품절관리 페이지로 리다이렉트
    """
    from django.shortcuts import redirect
    from django.contrib import messages
    from .models import OutOfStockMapping, OptionPlatformDetail

    # (A) OutOfStockMapping 전체 삭제
    OutOfStockMapping.objects.all().delete()

    # (B) 추가로 OptionPlatformDetail도 지우고 싶다면
    # OptionPlatformDetail.objects.all().delete()

    # (C) 완료 후 메시지 표시
    messages.success(request, "전체 데이터가 삭제되었습니다.")
    return redirect('out_of_stock_management')



# def action_option_mapping(request):
#     """
#     하나의 form에서 여러 action(upload_excel, delete_multiple, ST_stock_update 등)을 처리.
#     여기서는 ST_stock_update 시, 전체 OptionPlatformDetail 에 대해
#     `seller_tool_stock`를 일괄 업데이트한다.
#     """
#     from django.shortcuts import redirect
#     from django.contrib import messages
#     import logging
#     logger = logging.getLogger(__name__)

#     if request.method == "POST":
#         action = request.POST.get('action','').strip()
#         logger.debug(f"[action_option_mapping] action={action}")

#         # ─────────────────────────────────────────
#         # (A) "셀러툴재고 (ST_stock_update)" 버튼
#         # ─────────────────────────────────────────
#         if action == 'ST_stock_update':
#             from .models import OptionPlatformDetail
#             from .api_clients import get_inventory_by_option_codes

#             # 1) 업데이트 대상: 전체 OptionPlatformDetail (페이지/체크박스 무시)
#             details_qs = OptionPlatformDetail.objects.select_related('option_mapping').all()
#             logger.debug(f"[ST_stock_update] details_qs count={details_qs.count()}")

#             if not details_qs.exists():
#                 messages.warning(request, "업데이트할 OptionPlatformDetail 데이터가 없습니다.")
#                 return redirect('option_mapping')

#             # 2) 모든 옵션코드(option_mapping.option_code) 수집
#             code_list = []
#             for detail_obj in details_qs:
#                 if detail_obj.option_mapping and detail_obj.option_mapping.option_code:
#                     code_list.append(detail_obj.option_mapping.option_code)
#             # 중복제거
#             code_list = list(set(code_list))

#             logger.debug(f"[ST_stock_update] code_list={code_list}")

#             if not code_list:
#                 messages.warning(request, "옵션코드가 존재하지 않습니다.")
#                 return redirect('option_mapping')

#             # 3) 셀러툴 API → 재고 정보 가져오기
#             stock_map = get_inventory_by_option_codes(code_list)
#             logger.debug(f"[ST_stock_update] stock_map={stock_map}")
#             # 예: {"ABC123": 10, "XYZ999": 0, ...}

#             # 4) DB 반영: OptionPlatformDetail 의 `seller_tool_stock` 필드 업데이트
#             updated_count = 0
#             for detail_obj in details_qs:
#                 # detail_obj.option_mapping.option_code 로 셀러툴 측 재고 확인
#                 if detail_obj.option_mapping:
#                     code = detail_obj.option_mapping.option_code
#                     old_stock = getattr(detail_obj, "seller_tool_stock", 0)  # 기존값
#                     new_stock = stock_map.get(code, 0)                       # API 응답값

#                     if new_stock != old_stock:
#                         # 바뀐 경우만 update
#                         detail_obj.seller_tool_stock = new_stock
#                         detail_obj.save()
#                         updated_count += 1

#             messages.success(request, f"{updated_count}건의 셀러툴재고가 갱신되었습니다.")
#             return redirect('option_mapping')

#         # B) 선택 삭제
#         elif action == 'delete_multiple':
#             mapping_ids = request.POST.getlist('mapping_ids', [])
#             logger.debug(f"[delete_multiple] mapping_ids={mapping_ids}")
            
#             if not mapping_ids:
#                 messages.error(request, "삭제할 항목이 선택되지 않았습니다.")
#                 return redirect('option_mapping')

#             qs = OptionMapping.objects.filter(id__in=mapping_ids)
#             count = qs.count()
#             logger.debug(f"[delete_multiple] qs.count={count}")
#             qs.delete()
            
#             messages.success(request, f"{count}건이 삭제되었습니다.")
#             return redirect('option_mapping')

#         # 그 외 다른 action => 그냥 리다이렉트
#         messages.warning(request, "알 수 없는 동작입니다.")
#         return redirect('option_mapping')

#     # GET -> option_mapping 페이지로
#     return redirect('option_mapping')



# def option_mapping(request):
#     """
#     - 기존 OptionMapping.objects.all() 대신,
#       OptionPlatformDetail.objects.select_related('option_mapping') 로 목록 구성
#     - 검색(search_option_code)은 option_mapping__option_code 에 icontains
#     - 페이지네이션 적용
#     - 템플릿에 넘길 때는 details로 넘겨주고,
#       details를 {{ row }} 로 순회하며 row.option_mapping.XXX / row.platform_option_id 등 접근
#     """
#     from django.shortcuts import render
#     from django.core.paginator import Paginator
#     from .models import OptionPlatformDetail

#     # 검색 파라미터
#     search_option_code = request.GET.get('search_option_code', '').strip()

#     # 1) QuerySet: platform_details
#     details_qs = OptionPlatformDetail.objects.select_related('option_mapping').order_by('-updated_at')

#     # 2) 검색 조건: option_mapping__option_code
#     if search_option_code:
#         details_qs = details_qs.filter(option_mapping__option_code__icontains=search_option_code)

#     # 3) 페이지네이션
#     paginator = Paginator(details_qs, 20)
#     page_number = request.GET.get('page', 1)
#     page_obj = paginator.get_page(page_number)

#     # elided_page_range
#     page_range_custom = page_obj.paginator.get_elided_page_range(
#         page_obj.number, on_each_side=2, on_ends=1
#     )

#     # 4) 예시: 미매칭 옵션코드 (샘플)
#     unmatched_options = [
#         {"option_code": "ABC123", "product_name": "우리상품A"},
#         {"option_code": "DEF456", "product_name": "우리상품B"},
#         {"option_code": "GHI789", "product_name": "우리상품C"},
#     ]

#     context = {
#         "details": page_obj.object_list,   # ← 페이지 객체의 실제 데이터
#         "page_obj": page_obj,
#         "page_range_custom": page_range_custom,

#         "search_option_code": search_option_code,
#         "unmatched_options": unmatched_options,
#     }
#     return render(request, 'delayed_management/option_mapping.html', context)



def update_naver_product_list(request):
    import logging
    from django.http import JsonResponse
    
    from .api_clients import NAVER_ACCOUNTS, fetch_naver_products_with_details
    from .models import (
        ExternalProductItem,
        ExternalProductOption,
        OptionMapping,
        OptionPlatformDetail,
    )

    logger = logging.getLogger(__name__)

    account_name = request.GET.get('account_name', '').strip()
    if not account_name:
        return JsonResponse({"error": "account_name이 없습니다."}, status=400)

    # 1) 네이버 계정 찾기
    account_info = None
    for acct in NAVER_ACCOUNTS:
        if account_name in acct['names']:
            account_info = acct
            break

    if not account_info:
        msg = f"[update_naver_product_list] 계정 '{account_name}'을 NAVER_ACCOUNTS에서 찾을 수 없습니다."
        logger.warning(msg)
        return JsonResponse({"error": msg}, status=400)

    logger.info(f"[update_naver_product_list] Found account_info: {account_info}")

    # 2) 네이버 상품/옵션 목록 가져오기
    is_ok, detailed_list = fetch_naver_products_with_details(account_info)
    if not is_ok:
        logger.error(f"[update_naver_product_list] fetch fail: {detailed_list}")
        return JsonResponse(
            {"error": "네이버 상품목록 조회 실패", "detail": detailed_list},
            status=400
        )

    logger.debug(
        f"[update_naver_product_list] fetch_naver_products_with_details → "
        f"is_ok={is_ok}, detail_list_len={len(detailed_list)}"
    )

    flattened_rows = []

    # (B) 상세 데이터(ExternalProductItem / ExternalProductOption)
    for idx, prod in enumerate(detailed_list, start=1):
        origin_no   = prod.get("originProductNo")
        product_nm  = prod.get("productName", "")
        rep_img     = prod.get("representativeImage", {})
        sale_price  = prod.get("salePrice", 0)
        stock_qty   = prod.get("stockQuantity", 0)
        seller_code_info = prod.get("sellerCodeInfo", {})

        if isinstance(rep_img, dict):
            rep_img_url = rep_img.get("url", "")
        elif isinstance(rep_img, str):
            rep_img_url = rep_img
        else:
            rep_img_url = ""

        seller_mgmt_code = ""
        if isinstance(seller_code_info, dict):
            seller_mgmt_code = seller_code_info.get("sellerManagerCode", "")
        elif isinstance(seller_code_info, str):
            seller_mgmt_code = seller_code_info

        # (B1) ExternalProductItem upsert
        product_item, created = ExternalProductItem.objects.update_or_create(
            origin_product_no=origin_no,
            defaults={
                "product_name": product_nm,
                "representative_image": rep_img_url,
                "sale_price": sale_price,
                "stock_quantity": stock_qty,
                "seller_code_info": seller_mgmt_code,
            }
        )

        # (B2) 옵션 리스트
        option_list = prod.get("optionCombinations", [])
        if not option_list:
            # 옵션 없는 단일상품
            db_opt, opt_created = ExternalProductOption.objects.update_or_create(
                product=product_item,
                option_id=None,
                defaults={
                    "store_name": account_name,  # <-- 스토어명 추가
                    "option_name1": None,
                    "option_name2": None,
                    "stock_quantity": 0,
                    "price": 0,
                    "seller_manager_code": ""
                }
            )
            flattened_rows.append({
                "option_code": "",      
                "optionID": "",         
                "representative_image": rep_img_url,
                "option_name1": "",
                "option_name2": "",
                "product_name": product_nm,
                "option_stock": "",
                "sale_price": sale_price,
                "option_price": "",
                "origin_product_no": origin_no,
            })
            continue

        # (B3) 옵션 여러개
        for combo_idx, combo in enumerate(option_list, start=1):
            opt_id    = combo.get("id")
            opt_nm1   = combo.get("optionName1", "")
            opt_nm2   = combo.get("optionName2", "")
            opt_stk   = combo.get("stockQuantity", 0)
            opt_price = combo.get("price", 0)
            opt_code  = combo.get("sellerManagerCode", "")

            db_opt, created_opt = ExternalProductOption.objects.update_or_create(
                product=product_item,
                option_id=opt_id,
                defaults={
                    "store_name": account_name,         # <-- 스토어명 추가
                    "option_name1": opt_nm1,
                    "option_name2": opt_nm2,
                    "stock_quantity": opt_stk,
                    "price": opt_price,
                    "seller_manager_code": opt_code
                }
            )
            logger.debug(f"      [{combo_idx}/{len(option_list)}] option_id={opt_id}, created={created_opt}")

            flattened_rows.append({
                "option_code": opt_code,
                "optionID": opt_id,
                "representative_image": rep_img_url,
                "option_name1": opt_nm1,
                "option_name2": opt_nm2,
                "product_name": product_nm,
                "option_stock": opt_stk,
                "sale_price": sale_price,
                "option_price": opt_price,
                "origin_product_no": origin_no,
            })

    # (C) OptionPlatformDetail upsert (동일)
    from .models import OptionPlatformDetail, OptionMapping
    for row in flattened_rows:
        code       = row.get("option_code") or ""
        opt_id     = row.get("optionID") or ""
        stock_qty  = row.get("option_stock") or 0
        price_val  = row.get("sale_price") or 0
        product_nm = row.get("product_name") or ""

        mapping_obj = OptionMapping.objects.filter(option_code=code).first()
        if not mapping_obj:
            continue

        defaults_data = {
            "order_product_name":  product_nm,
            "order_option_name":   f"{row['option_name1']} / {row['option_name2']}".strip(" / "),
            "stock":               stock_qty,
            "price":               price_val,
            "seller_manager_code": code,
            "representative_image": row.get("representative_image") or "",
            "origin_product_no":   row.get("origin_product_no") or "",
        }

        detail_obj, created_det = OptionPlatformDetail.objects.update_or_create(
            option_mapping     = mapping_obj,
            platform_name      = account_name,  # 네이버 스토어 이름
            platform_option_id = str(opt_id),
            defaults={
                "platform_product_id": str(row["origin_product_no"] or ""),
                **defaults_data
            }
        )

    return JsonResponse({
        "message": f"{account_name} 상품목록(옵션별 행) 업데이트 & DB 저장 완료",
        "count": len(flattened_rows),
        "products": flattened_rows
    })


def update_coupang_product_list(request):
    import logging
    from django.http import JsonResponse
    
    from .api_clients import (
        COUPANG_ACCOUNTS,
        fetch_coupang_all_seller_products,
        fetch_coupang_seller_product_with_options
    )
    from .models import (
        ExternalProductItem,
        ExternalProductOption,
        OptionMapping,
        OptionPlatformDetail
    )

    logger = logging.getLogger(__name__)

    account_name = request.GET.get('account_name', '').strip()
    if not account_name:
        return JsonResponse({"error": "account_name이 없습니다."}, status=400)

    # (1) 쿠팡 계정 찾기
    account_info = None
    for acct in COUPANG_ACCOUNTS:
        if account_name in acct['names']:
            account_info = acct
            break
    if not account_info:
        msg = f"[update_coupang_product_list] '{account_name}' 계정을 찾을 수 없습니다."
        logger.warning(msg)
        return JsonResponse({"error": msg}, status=400)

    logger.debug(f"[update_coupang_product_list] account_name={account_name}, account_info={account_info}")

    # (2) 등록상품 목록 조회
    is_ok, big_list = fetch_coupang_all_seller_products(account_info, max_per_page=50)
    if not is_ok:
        logger.error(f"[update_coupang_product_list] 상품목록 조회 실패: {big_list}")
        return JsonResponse({"error": "쿠팡 상품목록 조회 실패", "detail": big_list}, status=400)

    logger.info(f"[update_coupang_product_list] total sellerProduct count={len(big_list)}")

    grand_flattened = []

    for idx, info in enumerate(big_list, start=1):
        seller_product_id = info.get("sellerProductId")
        display_name      = info.get("sellerProductName", "(상품명없음)")

        if not seller_product_id:
            continue

        # (3A) 각 상품 옵션목록 Flatten
        is_ok2, flattened_list = fetch_coupang_seller_product_with_options(
            account_info, seller_product_id
        )
        if not is_ok2:
            logger.warning(f"[update_coupang_product_list] seller_product_id={seller_product_id} 옵션조회 실패 → skip")
            continue

        if not flattened_list:
            continue

        # (3B) ExternalProductItem upsert
        first_opt = flattened_list[0]
        rep_img_url = first_opt.get("representativeImage") or None
        first_stock = first_opt.get("optionStock", 0)
        first_price = first_opt.get("salePrice", 0)

        product_item, item_created = ExternalProductItem.objects.update_or_create(
            origin_product_no=seller_product_id,
            defaults={
                "product_name":         display_name,
                "representative_image": rep_img_url,
                "sale_price":           first_price,
                "stock_quantity":       first_stock,
                "seller_code_info":     "",  # 쿠팡은 별도 sellerCodeInfo가 없으므로
            }
        )

        # (3C) 옵션들 반복
        for row in flattened_list:
            vendor_item_id   = row.get("optionID", "")
            option_seller_cd = row.get("optionSellerCode", "")
            item_name        = row.get("optionName1", "")
            rep_img          = row.get("representativeImage") or None
            stock_qty        = row.get("optionStock", 0)
            sale_price_val   = row.get("salePrice", 0)

            db_opt, opt_created = ExternalProductOption.objects.update_or_create(
                product=product_item,
                option_id=vendor_item_id,
                defaults={
                    "store_name": account_name,           # <-- 스토어명 추가
                    "option_name1":        item_name,
                    "option_name2":        item_name,
                    "stock_quantity":      stock_qty,
                    "price":               sale_price_val,
                    "seller_manager_code": option_seller_cd,
                }
            )

            # (3D) OptionPlatformDetail upsert
            mapping_obj = OptionMapping.objects.filter(option_code=option_seller_cd).first()
            if mapping_obj:
                detail_defaults = {
                    "order_product_name":  display_name,
                    "order_option_name":   item_name,
                    "stock":               stock_qty,
                    "price":               sale_price_val,
                    "seller_manager_code": option_seller_cd,
                    "representative_image": rep_img or "",
                    "origin_product_no":   str(seller_product_id),
                }
                OptionPlatformDetail.objects.update_or_create(
                    option_mapping     = mapping_obj,
                    platform_name      = account_name,
                    platform_option_id = vendor_item_id,
                    defaults={
                        "platform_product_id": str(seller_product_id),
                        **detail_defaults
                    }
                )

            grand_flattened.append({
                "optionID":             vendor_item_id,
                "option_code":          option_seller_cd,
                "representative_image": rep_img,
                "option_name1":         item_name,
                "option_name2":         item_name,
                "product_name":         display_name,
                "option_stock":         stock_qty,
                "sale_price":           sale_price_val,
                "option_price":         sale_price_val,
                "origin_product_no":    row.get("originProductNo", "") or row.get("sellerProductId", ""),
            })

    logger.info(
        f"[update_coupang_product_list] 최종 Flattened={len(grand_flattened)} rows 저장 완료."
    )

    return JsonResponse({
        "message": f"{account_name} 상품목록(옵션별 행) 업데이트 & DB 저장 완료",
        "count": len(grand_flattened),
        "products": grand_flattened
    })


def api_option_list_view(request):
    """
    ExternalProductOption 테이블을 조회하여,
    - 상품명(product__product_name) or
    - 옵션코드(seller_manager_code)
    로 검색할 수 있는 리스트 페이지.

    (option_id, option_name1/2, stock_quantity 등도 함께 표시)
    """
    search_query = request.GET.get('search_query', '').strip()

    # 1) ExternalProductOption 목록 (product select_related)
    qs = ExternalProductOption.objects.select_related('product').order_by('-id')

    # 2) 검색 조건 적용
    #    상품명 or 옵션코드
    if search_query:
        qs = qs.filter(
            Q(product__product_name__icontains=search_query) |
            Q(seller_manager_code__icontains=search_query) |
            Q(option_id__icontains=search_query)
        )

    # 3) 페이지네이션 (페이지당 50개)
    paginator = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # elided_page_range (페이지 버튼이 많아질 때 간략히 표시)
    page_range_custom = page_obj.paginator.get_elided_page_range(
        page_obj.number, on_each_side=2, on_ends=1
    )

    # 4) 템플릿 컨텍스트
    context = {
        "options": page_obj.object_list,       # 실제 옵션 목록
        "page_obj": page_obj,
        "page_range_custom": page_range_custom,
        "search_query": search_query,          # 템플릿에서 검색어 유지
    }
    return render(request, "delayed_management/api_list.html", context)



def option_id_stock_update_view(request):
    import logging, json
    logger = logging.getLogger(__name__)

    from django.http import JsonResponse
    from .models import (
        OptionPlatformDetail,
        OutOfStockMapping,  # 미매칭 시 OutOfStockMapping도 처리할 수 있음
    )
    from .api_clients import (
        NAVER_ACCOUNTS, COUPANG_ACCOUNTS,
        fetch_naver_option_stock,
        get_coupang_item_inventories,
    )

    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Only POST method allowed"}, status=405)

    try:
        body = request.body.decode('utf-8')
        data = json.loads(body)  # { "detail_ids": [...] }
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON body"}, status=400)

    raw_list = data.get("detail_ids", [])
    raw_list = [str(x).strip() for x in raw_list if str(x).strip()]
    if not raw_list:
        return JsonResponse({"success": False, "message": "선택된 옵션이 없습니다."}, status=400)

    updated_count = 0

    # 분리: detail vs outofstock
    detail_ids = []
    outofstock_ids = []

    for val in raw_list:
        if "-" not in val:
            logger.debug(f"[option_id_stock_update] '{val}' 잘못된 형식 → skip")
            continue
        row_type, pk_str = val.split("-", 1)
        try:
            pk_val = int(pk_str)
        except ValueError:
            logger.debug(f"[option_id_stock_update] '{val}' pk 변환 실패 → skip")
            continue

        if row_type == "detail":
            detail_ids.append(pk_val)
        elif row_type == "outofstock":
            outofstock_ids.append(pk_val)
        else:
            logger.debug(f"[option_id_stock_update] 알수없는 row_type={row_type} → skip")

    # (A) detail_ids → OptionPlatformDetail 조회 + API조회
    if detail_ids:
        details_qs = OptionPlatformDetail.objects.select_related('option_mapping')\
                         .filter(id__in=detail_ids)
        for d in details_qs:
            platform    = (d.platform_name or "").strip()
            vendor_id   = (d.platform_option_id or "").strip()
            origin_no   = (d.origin_product_no or "").strip()

            # 네이버 or 쿠팡 계정 찾기
            account_info = None
            # 1) 네이버?
            for acct in NAVER_ACCOUNTS:
                if platform in acct.get('names', []):
                    account_info = acct
                    break

            if account_info:
                # 네이버 로직
                if not origin_no:
                    logger.debug(f"[option_id_stock_update] detail.id={d.id} → origin_no 없음, skip")
                    continue
                is_ok, combos = fetch_naver_option_stock(account_info, origin_no)
                if not is_ok:
                    logger.debug(f"[option_id_stock_update] 네이버 API fail: {combos}")
                    continue
                combo = next((c for c in combos if str(c["id"]) == vendor_id), None)
                if not combo:
                    logger.debug(f"[option_id_stock_update] {vendor_id} 옵션ID 못찾음")
                    continue
                old_stock = d.stock
                new_stock = combo.get("stockQuantity", 0)
                if new_stock != old_stock:
                    d.stock = new_stock
                    d.price = combo.get("price", 0)
                    d.save()
                    updated_count += 1
                continue

            # 2) 쿠팡?
            account_info = None
            for acct in COUPANG_ACCOUNTS:
                if platform in acct.get('names', []):
                    account_info = acct
                    break

            if account_info:
                if not vendor_id:
                    logger.debug(f"[option_id_stock_update] detail.id={d.id} → vendor_item_id 없음, skip")
                    continue
                is_ok, item_data = get_coupang_item_inventories(account_info, vendor_id)
                if not is_ok:
                    logger.debug(f"[option_id_stock_update] 쿠팡 API fail: {item_data}")
                    continue
                old_stock = d.stock
                new_stock = item_data.get("amountInStock", 0)
                new_price = item_data.get("salePrice", 0)
                if new_stock != old_stock:
                    d.stock = new_stock
                    d.price = new_price
                    d.save()
                    updated_count += 1
            else:
                logger.debug(f"[option_id_stock_update] Unknown platform='{platform}', skip")

    # (B) outofstock_ids → 미매칭(OutOfStockMapping) 처리 (원하는 작업이 있다면)
    #    예: 단순 로그 or 삭제 or 무시
    if outofstock_ids:
        out_qs = OutOfStockMapping.objects.filter(id__in=outofstock_ids)
        logger.debug(f"[option_id_stock_update] outofstock_ids={outofstock_ids}, count={out_qs.count()}")
        # 예: out_qs.delete() or 다른 처리
        # 여기서는 아무것도 안 한다고 가정
        pass

    return JsonResponse({
        "success": True,
        "updated_count": updated_count,
        "message": f"옵션ID재고 업데이트 완료: {updated_count}건 변경됨."
    })




def do_out_of_stock_view(request):
    import logging, json
    logger = logging.getLogger(__name__)

    from django.http import JsonResponse
    from .models import (
        OptionPlatformDetail,
        OutOfStockMapping
    )
    from .api_clients import (
        naver_update_option_stock,
        coupang_update_item_stock,
    )

    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Only POST method is allowed."
        }, status=405)

    try:
        body = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON body"}, status=400)

    raw_list = body.get("detail_ids", [])
    raw_list = [x.strip() for x in raw_list if x.strip()]
    if not raw_list:
        return JsonResponse({"success": False, "message": "선택된 옵션이 없습니다."}, status=400)

    updated_count = 0

    # 1) 분리
    detail_ids = []
    outofstock_ids = []

    for val in raw_list:
        if "-" not in val:
            continue
        row_type, pk_str = val.split("-",1)
        try:
            pk_val = int(pk_str)
        except ValueError:
            continue

        if row_type == "detail":
            detail_ids.append(pk_val)
        elif row_type == "outofstock":
            outofstock_ids.append(pk_val)

    # 2) detail_ids → OptionPlatformDetail
    if detail_ids:
        details_qs = OptionPlatformDetail.objects.filter(id__in=detail_ids)
        for d in details_qs:
            platform  = (d.platform_name or "").strip()
            option_id = (d.platform_option_id or "").strip()
            origin_no = (d.origin_product_no or "").strip()

            if platform in ["니뜰리히","수비다","수비다 SUBIDA","노는개최고양","노는 개 최고양","아르빙"]:
                is_ok, msg = naver_update_option_stock(
                    origin_no,
                    option_id,
                    new_stock=0,
                    platform_name=platform
                )
                if is_ok:
                    d.stock = 0
                    d.save()
                    updated_count += 1
                else:
                    logger.warning(f"[NAVER 품절실패] detail.id={d.id}, msg={msg}")
            elif platform in ["쿠팡01", "쿠팡02"]:
                is_ok, msg = coupang_update_item_stock(
                    vendor_item_id=option_id,
                    new_stock=0,
                    platform_name=platform
                )
                if is_ok:
                    d.stock = 0
                    d.save()
                    updated_count += 1
                else:
                    logger.warning(f"[쿠팡 품절실패] detail.id={d.id}, msg={msg}")
            else:
                logger.debug(f"[Unknown Platform] {platform}, skip do_out_of_stock.")

    # 3) outofstock_ids → 미매칭 항목(OutOfStockMapping)
    #    필요시 여기서도 품절처리(??) or 삭제
    if outofstock_ids:
        out_qs = OutOfStockMapping.objects.filter(id__in=outofstock_ids)
        logger.debug(f"[do_out_of_stock_view] outofstock_ids={outofstock_ids}, qs.count={out_qs.count()}")
        # 예: out_qs.delete() or pass
        # updated_count += out_qs.count() if deleting? 
        pass

    return JsonResponse({
        "success": True,
        "updated_count": updated_count,
        "message": f"{updated_count}건 품절처리 완료."
    })



def add_stock_9999_view(request):
    import logging, json
    logger = logging.getLogger(__name__)
    from django.http import JsonResponse
    from .models import OptionPlatformDetail, OutOfStockMapping
    from .api_clients import (
        put_naver_option_stock_9999,
        put_coupang_option_stock_9999,
    )

    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Only POST method allowed"}, status=405)

    try:
        body = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "Invalid JSON body"}, status=400)

    raw_list = body.get('detail_ids', [])
    raw_list = [x.strip() for x in raw_list if x.strip()]
    if not raw_list:
        return JsonResponse({"success":False,"message":"선택된 항목이 없습니다."}, status=400)

    updated_count = 0

    detail_ids = []
    outofstock_ids = []
    for val in raw_list:
        if "-" not in val:
            continue
        row_type, pk_str = val.split("-",1)
        try:
            pk_val = int(pk_str)
        except ValueError:
            continue

        if row_type == "detail":
            detail_ids.append(pk_val)
        elif row_type == "outofstock":
            outofstock_ids.append(pk_val)

    # (A) detail_ids → OptionPlatformDetail
    if detail_ids:
        details_qs = OptionPlatformDetail.objects.filter(id__in=detail_ids)
        for d in details_qs:
            platform = (d.platform_name or "").strip()
            if platform in ["니뜰리히","수비다 SUBIDA","노는 개 최고양","아르빙"]:
                is_ok, msg = put_naver_option_stock_9999(
                    origin_no=d.origin_product_no,
                    option_id=d.platform_option_id,
                    platform_name=platform
                )
                if is_ok:
                    d.stock = 9999
                    d.save()
                    updated_count += 1
            elif platform in ["쿠팡01","쿠팡02"]:
                is_ok, msg = put_coupang_option_stock_9999(
                    vendor_item_id=d.platform_option_id,
                    platform_name=platform
                )
                if is_ok:
                    d.stock = 9999
                    d.save()
                    updated_count += 1
            else:
                logger.debug(f"[add_stock_9999_view] Unknown platform={platform}")

    # (B) outofstock_ids → 미매칭
    if outofstock_ids:
        out_qs = OutOfStockMapping.objects.filter(id__in=outofstock_ids)
        logger.debug(f"[add_stock_9999_view] outofstock_ids={outofstock_ids}, qs.count={out_qs.count()}")
        # 필요시 로직(삭제/무시/로그)
        # updated_count += something if doing an action
        pass

    return JsonResponse({
        "success": True,
        "updated_count": updated_count,
        "message": f"{updated_count}건 재고를 9999로 변경했습니다."
    })


def update_seller_tool_and_increase_stock_view(request):
    """
    1) OutOfStockMapping → option_code들을 모아서,
    2) OptionPlatformDetail 중 해당 option_code가 있는 항목 전부 찾기
    3) seller_tool 재고 업데이트 (get_inventory_by_option_codes)
    4) 차이가 있으면 (새재고 - old재고):
       - 1~10 증가: 해당만큼 stock+=difference
       - 11 이상 증가: stock=9999
    5) 네이버/쿠팡 API 호출도 같이 수행
    """
    import logging
    logger = logging.getLogger(__name__)
    from django.shortcuts import redirect
    from django.contrib import messages

    from .models import OutOfStockMapping, OptionPlatformDetail
    from .api_clients import (
        get_inventory_by_option_codes,  # 셀러툴로부터 재고맵을 가져오는 함수 (option_code -> 재고수량)
        naver_update_option_stock,      # 재고=임의값으로 세팅
        coupang_update_item_stock,      # 재고=임의값으로 세팅
        put_naver_option_stock_9999,    # 재고=9999
        put_coupang_option_stock_9999   # 재고=9999
    )

    # 1) OutOfStockMapping 전체 → option_code만 추출
    outofstock_list = OutOfStockMapping.objects.all()
    if not outofstock_list.exists():
        messages.warning(request, "OutOfStockMapping(품절관리) 데이터가 없습니다.")
        return redirect('out_of_stock_management')

    code_list = []
    for out_item in outofstock_list:
        if out_item.option_code:
            code_list.append(out_item.option_code.strip())
    code_list = list(set(code_list))  # 중복 제거

    if not code_list:
        messages.warning(request, "옵션코드가 존재하지 않아 셀러툴 재고 업데이트가 불가합니다.")
        return redirect('out_of_stock_management')

    logger.debug(f"[update_seller_tool_and_increase_stock_view] code_list={code_list}")

    # 2) 셀러툴 API를 통해 재고 정보 가져오기
    stock_map = get_inventory_by_option_codes(code_list)
    # stock_map 예: { "ABC123": 15, "XYZ777": 999, ... }

    # 3) OptionPlatformDetail 중 option_mapping.option_code in code_list
    #    select_related('option_mapping')로 미리 조인
    details_qs = OptionPlatformDetail.objects.select_related('option_mapping')\
                    .filter(option_mapping__option_code__in=code_list)
    if not details_qs.exists():
        messages.warning(request, "해당 옵션코드(OutOfStockMapping)와 일치하는 OptionPlatformDetail 데이터가 없습니다.")
        return redirect('out_of_stock_management')

    logger.debug(f"[update_seller_tool_and_increase_stock_view] details_qs.count={details_qs.count()}")

    updated_st_count = 0  # 셀러툴재고 수정된 갯수
    action_count = 0      # 실제 옵션ID재고 증가/9999 처리된 횟수

    for detail_obj in details_qs:
        if not detail_obj.option_mapping:
            continue

        code = detail_obj.option_mapping.option_code.strip()
        old_seller_tool = detail_obj.seller_tool_stock
        new_seller_tool = stock_map.get(code, 0)

        # 3A) "셀러툴재고" 업데이트 (만약 값이 바뀌었다면)
        if new_seller_tool != old_seller_tool:
            detail_obj.seller_tool_stock = new_seller_tool
            detail_obj.save()
            updated_st_count += 1

            # 증가 폭 계산
            diff = new_seller_tool - old_seller_tool
            logger.debug(f"[seller_tool diff] code={code}, old={old_seller_tool}, new={new_seller_tool}, diff={diff}")

            # (a) diff>0 이면 옵션ID재고 증가 로직
            if diff > 0:
                platform = (detail_obj.platform_name or "").strip()
                origin_no_or_vendor = (detail_obj.origin_product_no or "").strip()
                opt_id = (detail_obj.platform_option_id or "").strip()

                if diff <= 10:
                    # (a1) diff <= 10 -> 기존 stock += diff
                    new_local_stock = (detail_obj.stock or 0) + diff
                    # 외부 API update
                    if platform in ["니뜰리히","수비다 SUBIDA","노는 개 최고양","아르빙"]:
                        # 네이버 update
                        success, msg = naver_update_option_stock(
                            origin_no=origin_no_or_vendor,
                            option_id=opt_id,
                            new_stock=new_local_stock,
                            platform_name=platform
                        )
                        if success:
                            detail_obj.stock = new_local_stock
                            detail_obj.save()
                            action_count += 1

                    elif platform in ["쿠팡01","쿠팡02"]:
                        # 쿠팡 update
                        success, msg = coupang_update_item_stock(
                            vendor_item_id=opt_id,
                            new_stock=new_local_stock,
                            platform_name=platform
                        )
                        if success:
                            detail_obj.stock = new_local_stock
                            detail_obj.save()
                            action_count += 1

                else:
                    # (a2) diff >= 11 -> 옵션ID재고=9999
                    if platform in ["니뜰리히","수비다 SUBIDA","노는 개 최고양","아르빙"]:
                        # 네이버 9999
                        success, msg = put_naver_option_stock_9999(
                            origin_no=origin_no_or_vendor,
                            option_id=opt_id,
                            platform_name=platform
                        )
                        if success:
                            detail_obj.stock = 9999
                            detail_obj.save()
                            action_count += 1

                    elif platform in ["쿠팡01","쿠팡02"]:
                        # 쿠팡 9999
                        success, msg = put_coupang_option_stock_9999(
                            vendor_item_id=opt_id,
                            platform_name=platform
                        )
                        if success:
                            detail_obj.stock = 9999
                            detail_obj.save()
                            action_count += 1
            # else: diff <= 0 이면 감소하거나 동일 -> 아무 처리X

    messages.success(request,
        f"셀러툴재고 {updated_st_count}건 업데이트 완료! "
        f"옵션ID재고 조정 {action_count}건 수행."
    )
    return redirect('out_of_stock_management')

@require_POST
def update_seller_tool_stock(request):
    """
    (1) OptionPlatformDetail 전체(or 필요한 범위)의 option_code들 모으기
    (2) 셀러툴 API → 재고조회
    (3) seller_tool_stock 필드 갱신
    (4) JSON 응답
    """
    try:
        # 1) 전체(혹은 특정 조건) OptionPlatformDetail
        details_qs = OptionPlatformDetail.objects.select_related('option_mapping').all()
        if not details_qs.exists():
            return JsonResponse({
                "success": False,
                "message": "OptionPlatformDetail 데이터가 없습니다."
            })

        # 2) option_code 수집
        code_list = []
        for detail in details_qs:
            if detail.option_mapping and detail.option_mapping.option_code:
                code_list.append(detail.option_mapping.option_code)
        code_list = list(set(code_list))  # 중복 제거

        if not code_list:
            return JsonResponse({
                "success": False,
                "message": "옵션코드가 없어 업데이트 불가"
            })

        # 3) 셀러툴 API 호출
        #    예: get_inventory_by_option_codes(["ABC123",...]) → { "ABC123":10, ... }
        from .api_clients import get_inventory_by_option_codes
        stock_map = get_inventory_by_option_codes(code_list)

        # 4) 갱신
        updated_count = 0
        for detail in details_qs:
            if detail.option_mapping:
                code = detail.option_mapping.option_code
                old_val = detail.seller_tool_stock or 0  # 필드명 가정
                new_val = stock_map.get(code, 0)
                if new_val != old_val:
                    detail.seller_tool_stock = new_val
                    detail.save()
                    updated_count += 1

        return JsonResponse({
            "success": True,
            "message": f"셀러툴 재고 업데이트 완료! ({updated_count}건 갱신)"
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": str(e),
        }, status=500)