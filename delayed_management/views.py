import openpyxl
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import DelayedOrderUploadForm, OptionStoreMappingUploadForm  
from .models import DelayedOrder, ProductOptionMapping ,OptionStoreMapping, DelayedShipment,DelayedShipmentGroup
from django.core.paginator import Paginator
from .api_clients import get_exchangeable_options
from .spreadsheet_utils import read_spreadsheet_data
from datetime import date, timedelta, timezone, datetime
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


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 필요 시 레벨 지정

# ==========================
# 1) "업로드" + "리스트 업로드" 함수
# ==========================
def upload_delayed_orders(request):
    print("=== DEBUG: upload_delayed_orders 뷰 진입 ===")

    # (A) 엑셀 업로드 (임시 세션 저장)
    if request.method == 'POST' and 'upload_excel' in request.POST:
        print("=== DEBUG: 엑셀 업로드 처리 시작 ===")
        form = DelayedOrderUploadForm(request.POST, request.FILES)
        if form.is_valid():
            print("=== DEBUG: 폼 유효성 검사 통과 ===")
            file = request.FILES['file']
            print(f"=== DEBUG: 업로드된 파일 이름: {file.name} ===")

            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active
            print(f"=== DEBUG: 시트명: {ws.title}, 행수: {ws.max_row}, 열수: {ws.max_column} ===")

            temp_orders = []
            for idx, row in enumerate(ws.iter_rows(values_only=True)):
                print(f"=== DEBUG: idx={idx}, row={row} ===")
                if idx == 0:
                    print("=== DEBUG: 헤더 행 스킵 ===")
                    continue
                if not row:
                    print("=== DEBUG: 빈 행, 스킵 ===")
                    continue
                if len(row) < 11:
                    print(f"=== DEBUG: 컬럼 부족 (현재 {len(row)}개), 스킵 ===")
                    continue

                option_code = (row[0] or "").strip()
                customer_name = (row[1] or "").strip()
                customer_contact = (row[2] or "").strip()
                order_product_name = (row[3] or "").strip()
                order_option_name = (row[4] or "").strip()
                quantity = (row[5] or "").strip()  # str
                seller_product_name = (row[6] or "").strip()
                seller_option_name = (row[7] or "").strip()
                order_number_1 = (row[8] or "").strip()
                order_number_2 = (row[9] or "").strip()
                store_name_raw = (row[10] or "").strip()

                if not option_code:
                    print("=== DEBUG: 옵션코드 없음, 스킵 ===")
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
                    'order_number_2': order_number_2,
                    'store_name': store_name_raw,
                }
                print(f"=== DEBUG: order_data={order_data} ===")
                temp_orders.append(order_data)

            request.session['delayed_orders_temp'] = temp_orders
            print(f"=== DEBUG: 임시저장 완료, {len(temp_orders)}건 ===")
            messages.success(request, f"{len(temp_orders)}건이 임시로 업로드되었습니다.")
            return redirect('upload_delayed_orders')
        else:
            print("=== DEBUG: 폼 유효성 검사 실패 ===")
            messages.error(request, "파일 업로드에 실패했습니다.")
            return redirect('upload_delayed_orders')

    # (B) "리스트 업로드" (최종 DB 저장) + 자동처리(옵션추출/스토어매핑/재입고동기화)
    elif request.method == 'POST' and 'finalize' in request.POST:
        print("=== DEBUG: 리스트 업로드(최종 저장) 처리 시작 ===")
        temp_orders = request.session.get('delayed_orders_temp', [])
        print(f"=== DEBUG: 현재 temp_orders 개수: {len(temp_orders)} ===")

        if not temp_orders:
            print("=== DEBUG: temp_orders 비어있음 ===")
            messages.error(request, "저장할 데이터가 없습니다.")
            return redirect('upload_delayed_orders')

        newly_created_codes = []
        row_count = 0
        group_token = str(uuid.uuid4())

        # 1) 실제 DB 저장
        for od in temp_orders:
            print(f"=== DEBUG: DB 저장 중: {od} ===")
            shipment = DelayedShipment.objects.create(
                option_code=od['option_code'],
                customer_name=od['customer_name'],
                customer_contact=od['customer_contact'],
                order_product_name=od['order_product_name'],
                order_option_name=od['order_option_name'],
                quantity=od['quantity'],
                seller_product_name=od['seller_product_name'],
                seller_option_name=od['seller_option_name'],
                order_number_1=od['order_number_1'],
                order_number_2=od['order_number_2'],
                store_name=od['store_name'],
                token = group_token,   # 동일하게!
            )
            row_count += 1
            newly_created_codes.append(shipment.option_code)

        # 2) 세션 제거
        request.session['delayed_orders_temp'] = []
        print(f"=== DEBUG: {row_count}건 DB 저장 완료 ===")

        # 3) 추가 자동 처리 (옵션추출, 스토어매핑, 재입고 동기화)
        extract_options_for_codes(newly_created_codes)
        store_mapping_for_codes(newly_created_codes)
        update_restock_for_codes(newly_created_codes)

        messages.success(
            request,
            f"{row_count}건의 지연 주문 정보가 DB에 저장되었습니다. "
            f"({len(newly_created_codes)}건에 대해 옵션추출, 스토어매핑, 재입고동기화까지 완료)"
        )
        return redirect('delayed_shipment_list')

    # (C) 임시 데이터(세션) 중 하나 삭제
    elif request.method == 'POST' and 'delete_item' in request.POST:
        print("=== DEBUG: 임시 데이터 삭제 요청 감지 ===")
        index_to_delete = request.POST.get('delete_index')
        if index_to_delete is not None:
            temp_orders = request.session.get('delayed_orders_temp', [])
            print(f"=== DEBUG: 삭제 요청 인덱스: {index_to_delete}, 현재 임시 데이터 건수: {len(temp_orders)} ===")
            try:
                idx = int(index_to_delete)
                if 0 <= idx < len(temp_orders):
                    deleted_item = temp_orders[idx]
                    del temp_orders[idx]
                    request.session['delayed_orders_temp'] = temp_orders
                    print(f"=== DEBUG: {deleted_item['option_code']} 삭제 완료 ===")
                    messages.success(request, "해당 항목이 삭제되었습니다.")
                else:
                    print("=== DEBUG: 잘못된 인덱스 ===")
                    messages.error(request, "잘못된 인덱스입니다.")
            except ValueError:
                print("=== DEBUG: 인덱스 변환 실패 ===")
                messages.error(request, "잘못된 요청입니다.")
        return redirect('upload_delayed_orders')

    # (D) GET 요청 → 업로드 폼 페이지 + 임시 데이터 테이블
    else:
        print("=== DEBUG: GET 요청으로 폼 페이지 로드 ===")
        temp_orders = request.session.get('delayed_orders_temp', [])
        print(f"=== DEBUG: 현재 세션 임시 데이터 {len(temp_orders)}건 ===")

        return render(request, 'delayed_management/upload_delayed_orders.html', {
            'form': DelayedOrderUploadForm(),
            'temp_orders': temp_orders,
        })


# ==========================
# 2) 하위 처리 함수들
# ==========================
def extract_options_for_codes(option_codes):
    for code in option_codes:
        qs = DelayedShipment.objects.filter(option_code=code)
        if not qs.exists():
            continue

        # 여러 건이 있을 수도 있으므로 (MultipleObjectsReturned 방지)
        # 하나씩 처리 or values_list() 등을 사용
        for shipment in qs:
            needed_qty = 1  # 기본값
            try:
                needed_qty = int(shipment.quantity)
            except (ValueError, TypeError):
                needed_qty = 1

            # 이제 needed_qty를 실제로 넘김
            exchange_list = get_exchangeable_options(code, needed_qty=needed_qty)
            exchange_str = ",".join(exchange_list) if exchange_list else "상담원 문의"

            # shipment 한 건씩 갱신 or bulk update
            shipment.exchangeable_options = exchange_str
            shipment.save()


def store_mapping_for_codes(option_codes):
    """
    방금 새로 생성된 DelayedShipment 레코드들에 대해 store_name 매핑
    """
    for code in option_codes:
        # 1) 해당 code의 DelayedShipment들
        qs = DelayedShipment.objects.filter(option_code=code)
        if not qs.exists():
            continue

        # 2) OptionStoreMapping 조회
        try:
            osm = OptionStoreMapping.objects.get(option_code=code)
            store_name = osm.store_name
        except OptionStoreMapping.DoesNotExist:
            store_name = ""

        # 3) update
        qs.update(store_name=store_name)


def update_restock_for_codes(option_codes):
    """
    스프레드시트 탭 or ETA_RANGES 등에 따라 expected_restock_date / status 업데이트
    (MultipleObjectsReturned 방지: filter() 사용)
    """
    # 예: ETA_RANGES
    ETA_RANGES = {
        'purchase': (14, 21),
        'shipping': (10, 14),
        'arrived': (7, 10),
        'document': (5, 7),
        'loading': (1, 4),
        'nopurchase': (0, 0),
    }

    today = date.today()

    for code in option_codes:
        qs = DelayedShipment.objects.filter(option_code=code)
        if not qs.exists():
            continue

        # 단순히 status='purchase' 라고 가정:
        # 실제로는 "sheet 탭" 로직 등을 참고해야 함
        # 여기서는 nopurchase → purchase 로 바꾸고, expected_restock_date 세팅
        for shipment in qs:
            if shipment.status == 'nopurchase':
                shipment.status = 'purchase'
            min_d, _ = ETA_RANGES.get(shipment.status, (0, 0))
            calc_date = today + timedelta(days=min_d) if min_d else None

            # expected_restock_date 매번 갱신
            shipment.expected_restock_date = calc_date
            # restock_date가 None이면 최초 설정
            if shipment.restock_date is None:
                shipment.restock_date = calc_date

            shipment.save()


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
            option_codes = request.POST.getlist('option_codes', [])
            if not option_codes:
                messages.error(request, "옵션추출할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            updated = 0
            for code in option_codes:
                # 교환가능 옵션 조회
                try:
                    shipment = DelayedShipment.objects.get(option_code=code)
                except DelayedShipment.DoesNotExist:
                    continue
                # needed_qty 등 추가 인자가 필요하면 수정
                exchangeable_list = get_exchangeable_options(code) 
                shipment.exchangeable_options = ",".join(exchangeable_list) if exchangeable_list else "상담원 문의"
                shipment.save()
                updated += 1

            messages.success(request, f"{updated}건 옵션추출 완료.")
            return redirect('delayed_shipment_list')

        # 2) 스토어 매핑 로직
        elif action == 'store_mapping':
            option_codes = request.POST.getlist('option_codes', [])
            updated = 0
            for code in option_codes:
                # DelayedShipment 여러 개일 수 있으므로 filter
                qs = DelayedShipment.objects.filter(option_code=code)
                if not qs.exists():
                    continue

                try:
                    mapping = OptionStoreMapping.objects.get(option_code=code)
                    store_name = mapping.store_name
                except OptionStoreMapping.DoesNotExist:
                    store_name = ""

                count = qs.update(store_name=store_name)
                updated += count

            messages.success(request, f"{updated}건 스토어 매핑 완료.")
            return redirect('delayed_shipment_list')

        # 3) 선택 삭제 로직
        elif action == 'delete_multiple':
            option_codes = request.POST.getlist('option_codes', [])
            if not option_codes:
                messages.error(request, "삭제할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            # 만약 option_code가 완전히 중복될 수 있다면, filter
            qs = DelayedShipment.objects.filter(option_code__in=option_codes)
            deleted_info = qs.delete()
            total_deleted = deleted_info[0]  # (개수, {model: num})
            messages.success(request, f"{total_deleted}건이 삭제되었습니다.")
            return redirect('delayed_shipment_list')

        elif action == 'send_sms':
            logger.debug("=== DEBUG: 문자 발송 로직 진입 ===")

            option_codes = request.POST.getlist('option_codes', [])
            if not option_codes:
                messages.error(request, "문자 발송할 항목이 선택되지 않았습니다.")
                return redirect('delayed_shipment_list')

            shipments = DelayedShipment.objects.filter(option_code__in=option_codes)
            if not shipments.exists():
                messages.error(request, "발송할 데이터가 없습니다.")
                return redirect('delayed_shipment_list')

            # (1) 모든 Shipment에 대해 동일 group_token을 새로 생성해서 덮어씌우는 경우
            group_token = str(uuid.uuid4())
            for s in shipments:
                s.token = group_token
                s.save()

            # (2) 메시지 생성
            messages_list = []
            for s in shipments:
                # store_name → channel_name
                channel_name = map_store_to_channel(s.store_name)
                pf_id = get_pfId_by_channel(channel_name)
                template_id = get_templateId_by_channel(channel_name)
                
                # 예: 알림톡인지 문자(SMS)인지 구분
                if pf_id:
                    s.send_type = 'KAKAO'
                else:
                    s.send_type = 'SMS'
                s.send_status = 'SENDING'
                s.save()

                # url_thx, url_change 만들 때, 로그로 확인
                url_thx = f"34.64.123.206/delayed/thank-you?action=wait&token={s.token}"
                url_change = f"34.64.123.206/delayed/option-change?action=change&token={s.token}"

                # >>> 추가한 로그
                logger.debug(f"=== DEBUG: url_thx={url_thx}")
                logger.debug(f"=== DEBUG: url_change={url_change}")

                if s.restock_date:
                    발송일자_str = s.restock_date.strftime('%Y-%m-%d')  # '2024-12-24' 형태
                else:
                    발송일자_str = ""

                # 치환 변수
                variables = {
                    '#{고객명}': s.customer_name or "",
                    '#{상품명}': s.order_product_name or "",
                    '#{옵션명}': s.order_option_name or "",
                    '#{발송일자}': 발송일자_str,
                    '#{교환옵션명}': s.exchangeable_options or "",
                    '#{채널명}': s.store_name or "", 
                    '#{url}':f"example.com",
                    '#{url_thx}': f"34.64.123.206/delayed/thank-you?action=wait&token={s.token}",
                    '#{url_change}': f"34.64.123.206/delayed/option-change?action=change&token={s.token}",
                    # '#{상담하기}': talkLink,
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
                    # 만약 문자일 경우 SMS/LMS 구분 로직이 필요할 수도 있고,
                    # Solapi V4 API에서 smsOptions 추가 등...
                    msg["text"] = f"[문자 테스트]\n안녕하세요 {s.customer_name or ''} 님,\n{(s.order_product_name or '')} 상품 안내"
                    # etc. (단순 예시)

                messages_list.append((s, msg))  # 모델 인스턴스와 msg 매핑

            if not messages_list:
                messages.warning(request, "발송할 메시지가 없습니다.")
                return redirect('delayed_shipment_list')

            # 실제 solapi 발송
            try:
                success_list, fail_list = solapi_send_messages(messages_list)
                
                # 성공한 옵션코드들만 flow_status='sent'로 업데이트
                DelayedShipment.objects.filter(option_code__in=success_list).update(flow_status='sent')

                # (선택) 실패한 목록은 flow_status='pre_send'로 되돌리거나 유지
                DelayedShipment.objects.filter(option_code__in=fail_list).update(flow_status='pre_send')

                messages.success(
                    request,
                    f"문자/알림톡 {len(success_list)}건 발송 성공, 실패 {len(fail_list)}건"
                )
            except Exception as e:
                logger.exception("=== DEBUG: 문자 발송 오류 발생 ===")
                messages.error(request, f"문자 발송 오류: {str(e)}")

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
    """
    if request.method == 'POST':
        option_code = request.POST.get('option_code', '').strip()
        if not option_code:
            messages.error(request, "옵션코드가 없습니다.")
            return redirect('restock_list')

        shipment = get_object_or_404(DelayedShipment, option_code=option_code)

        new_status = request.POST.get('status')
        new_eta = request.POST.get('eta')  # YYYY-MM-DD 형태 가정

        if new_status:
            shipment.status = new_status

        if new_eta:
            # 날짜 변환
            try:
                y, m, d = new_eta.split('-')
                shipment.eta = date(int(y), int(m), int(d))
            except ValueError:
                messages.error(request, "유효한 날짜 형식이 아닙니다.")
                return redirect('restock_list')

        shipment.save()
        messages.success(request, f"{option_code} 정보가 업데이트되었습니다.")
        return redirect('restock_list')

    # GET이면 목록 페이지로
    return redirect('restock_list')


tabs = ["구매된상품들", "배송중", "도착완료", "서류작성", "선적중"]




def update_restock_from_sheet(request):


    service_account_file = settings.SERVICE_ACCOUNT_FILE
    spreadsheet_id = "1qQfo2Pp-odUuYwKmQXNPv1phzK6Gi2JtlJYaaz3T1F0"

    client = get_gspread_client(service_account_file)
    sh = client.open_by_key(spreadsheet_id)

    tabs = ["구매된상품들", "배송중", "도착완료", "서류작성", "선적중"]

    ETA_RANGES = {
    'purchase':  (14, 21),
    'shipping':  (10, 14),
    'arrived':   (7, 10),
    'document':  (5, 7),
    'loading':   (1, 4),
    'nopurchase': (0, 0),
}

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
            if not row or len(row) < 1:
                continue

            option_code = row[0].strip()
            if not option_code:
                continue

            # 스프레드시트 탭 → DB status
            status_code = map_status(tab_name)

            # ETA 계산 (min_days만 사용)
            min_days, max_days = ETA_RANGES.get(status_code, (0,0))
            calc_date = today + timedelta(days=min_days) if min_days else None

            try:
                shipment = DelayedShipment.objects.get(option_code=option_code)
                # 1) 매번 expected_restock_date 갱신
                shipment.expected_restock_date = calc_date

                # 2) restock_date가 아직 None이면 (최초 설정 시점)만 넣고, 이미 있으면 변경하지 않음
                if shipment.restock_date is None:
                    shipment.restock_date = calc_date

                # 3) 상태도 갱신
                shipment.status = status_code
                shipment.save()
                total_updated += 1
            except DelayedShipment.DoesNotExist:
                pass

    messages.success(request, f"{total_updated}건 동기화 완료 (restock_date는 최초 1회만 설정, expected_restock_date는 매번 갱신).")
    return redirect('restock_management')


# Solapi API 환경변수
SOLAPI_API_KEY = config('SOLAPI_API_KEY', default=None)
SOLAPI_API_SECRET = config('SOLAPI_API_SECRET', default=None)
SOLAPI_SENDER_NUMBER = config('SOLAPI_SENDER_NUMBER', default='')  # 발신번호


def send_message_list(request):
    qs = DelayedShipment.objects.filter(flow_status='sent').order_by('-created_at')
    return render(request, 'delayed_management/send_message_list.html', {
        'shipments': qs
    })

def send_message_process(request):
    if request.method == 'POST':
        action = request.POST.get('action', '')
        shipment_ids = request.POST.getlist('shipment_ids', [])

        # (A) 선택 삭제(delete_multiple)
        if action == 'delete_multiple':
            if not shipment_ids:
                messages.error(request, "삭제할 항목이 선택되지 않았습니다.")
                return redirect('send_message_list')

            qs = DelayedShipment.objects.filter(id__in=shipment_ids)
            deleted_info = qs.delete()
            total_deleted = deleted_info[0]  # (삭제된 객체 수, { 'app.Model': count })
            messages.success(request, f"{total_deleted}건이 삭제되었습니다.")
            return redirect('send_message_list')

        # (B) 문자 발송(send_sms)
        elif action == 'send_sms':
            logger.debug("=== DEBUG: 문자 발송 로직 진입 ===")
            if not shipment_ids:
                messages.error(request, "문자 발송할 항목이 선택되지 않았습니다.")
                return redirect('send_message_list')

            shipments = DelayedShipment.objects.filter(id__in=shipment_ids)
            if not shipments.exists():
                messages.error(request, "발송할 데이터가 없습니다.")
                return redirect('send_message_list')

            # 그룹 토큰(같이 보내기 위해) 생성
            group_token = str(uuid.uuid4())
            for s in shipments:
                s.token = group_token
                s.save()

            # 메시지 생성
            messages_list = []
            for s in shipments:
                # store_name → channel_name
                channel_name = map_store_to_channel(s.store_name)
                pf_id = get_pfId_by_channel(channel_name)
                template_id = get_templateId_by_channel(channel_name)

                # 발송유형, 전송상태 설정
                if pf_id:
                    s.send_type = 'KAKAO'
                else:
                    s.send_type = 'SMS'
                s.send_status = 'SENDING'
                s.save()

                # 예) URL
                url_thx = f"34.64.123.206/delayed/thank-you?action=wait&token={s.token}"
                url_change = f"34.64.123.206/delayed/option-change?action=change&token={s.token}"
                logger.debug(f"=== DEBUG: url_thx={url_thx}")
                logger.debug(f"=== DEBUG: url_change={url_change}")

                발송일자_str = s.restock_date.strftime('%Y-%m-%d') if s.restock_date else ""

                # 치환 변수 (Solapi 알림톡)
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
                    msg["text"] = f"[문자 테스트]\n안녕하세요 {s.customer_name or ''}님,\n{s.order_product_name or ''} 안내"

                messages_list.append((s, msg))

            if not messages_list:
                messages.warning(request, "발송할 메시지가 없습니다.")
                return redirect('send_message_list')

            try:
                success_list, fail_list = solapi_send_messages(messages_list)
                DelayedShipment.objects.filter(id__in=success_list).update(flow_status='sent')
                messages.success(request, f"문자/알림톡 {len(success_list)}건 발송 성공, 실패 {len(fail_list)}건")
            except Exception as e:
                logger.exception("=== DEBUG: 문자 발송 오류 발생 ===")
                messages.error(request, f"문자 발송 오류: {str(e)}")

            return redirect('send_message_list')

    # 그 외(GET 등) 잘못된 요청이면 리스트 페이지로
    return redirect('send_message_list')



def solapi_send_messages(messages_list):
    """
    messages_list = [(shipment, msg), (shipment, msg), ...] 형태
    실제 Solapi에 전송 후, 성공/실패 여부에 따라
      - DelayedShipment.send_status = 'SUCCESS' or 'FAIL'로 업데이트
    """
    success_list = []
    fail_list = []

    # 요청 보낼 body 구조: {"messages": [ {to, from, kakaoOptions...}, ...]}
    body = {"messages": []}
    for s, msg_obj in messages_list:
        body["messages"].append(msg_obj)

    # **(1) 메시지 유형 식별** - kakaoOptions가 있으면 KAKAO, 없으면 SMS로 가정
        if "kakaoOptions" in msg_obj:
            s.send_type = "KAKAO"  
        else:
            s.send_type = "SMS"

    # Solapi 인증 헤더
    now_iso = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec='seconds')
    salt = str(uuid.uuid4())
    signature = make_solapi_signature(now_iso, salt, SOLAPI_API_SECRET)  # 별도 함수
    auth_header = f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={now_iso}, salt={salt}, signature={signature}"

    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_header
    }

    url = "https://api.solapi.com/messages/v4/send-many"
    logger.debug(f"=== DEBUG: solapi_send_messages -> POST {url}")
    logger.debug(f"=== DEBUG: payload={body}")
    logger.debug(f"=== DEBUG: headers={headers}")

    res = requests.post(url, json=body, headers=headers, timeout=10)
    logger.debug(f"=== DEBUG: 솔라피 응답 code={res.status_code} / body={res.text}")

    # 단순 예: status_code == 200이면 SUCCESS, 아니면 FAIL 처리
    # 실제로는 응답 body(JSON) parse 해서 "errorCode"나 "log" 등을 확인 가능
    if res.status_code == 200:
        # 전송 성공으로 간주(실제로는 부분 실패 있을 수 있으니 상세 parse 필요)
        for s, msg_obj in messages_list:
            s.send_status = 'SUCCESS'
            s.save()
            success_list.append(s.option_code)
    else:
        # 전송 실패
        for s, msg_obj in messages_list:
            # **(2) send_type=FAIL로 덮어쓰면, 어떤 발송수단 시도인지 알 수 없으니 
            #        필요하다면 그대로 KAKAO/SMS 유지 + send_status='FAIL'만 표기도 가능**
            s.send_type = 'FAIL'   
            s.send_status = 'FAIL'
            s.save()
            fail_list.append(s.option_code)

    return success_list, fail_list


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
    domain = getattr(settings, 'MY_SERVER_DOMAIN', 'https://34.64.123.206.com')
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
        "노는 개 최고양": "KA01PF241016104250071z8FktOivA0r",
        "아르빙": "KA01PF241016104450781C2ssOn2lCCM",
    }
    return pf_map.get(channel_name, "")

def get_templateId_by_channel(channel_name):
    """
    채널명 → templateId
    """
    tmpl_map = {
        "니뜰리히": "KA01TP2412240535576057F8eRaIgNOt",
        "수비다": "KA01TP2412240535576057F8eRaIgNOt",
        "노는 개 최고양": "KA01TP2412240535576057F8eRaIgNOt",
        "아르빙": "KA01TP2412240535576057F8eRaIgNOt",
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

    if not token:
        return HttpResponse("유효하지 않은 요청: token 없음", status=400)

    shipment = DelayedShipment.objects.filter(token=token).first()
    if not shipment:
        return HttpResponse("유효하지 않은 토큰", status=404)

    # 이미 waiting/changed_option 이 있다면 더 이상 변경 불가
    if shipment.waiting or shipment.changed_option:
        return HttpResponse("이미 처리된 내역이 존재합니다. 더 이상 변경할 수 없습니다.")

    if action == 'wait':
        shipment.waiting = True
        shipment.confirmed = True
        # 발송흐름 상태도 '확인완료'로
        shipment.flow_status = 'confirmed'
        shipment.save()
        return redirect('thank_you_view')

    elif action == 'change':
        # TODO: flow_status='confirmed' 는 옵션변경 후 최종 저장(옵션변경 완료 시점)에 세팅
        return redirect(f"/delayed/option-change/?token={token}")

    else:
        return HttpResponse("잘못된 action", status=400)

    
    
def thank_you_view(request):
    """
    "기다리기" 버튼을 클릭한 뒤 띄울 페이지.
    간단한 감사 메시지를 렌더링한다.
    """
    return render(request, 'delayed_management/thank_you.html')    

def option_change_view(request):
    token = request.GET.get('token', '')
    shipments = DelayedShipment.objects.filter(token=token)
    if not shipments.exists():
        return HttpResponse("유효하지 않은 토큰", status=404)

    # 각 품목별 실제 교환가능옵션을 구해 data 구성
    shipments_data = []
    for s in shipments:
        try:
            needed_qty = int(s.quantity or 1)
        except:
            needed_qty = 1
        # 실제 API에서 가져오기
        real_options = get_exchangeable_options(s.option_code, needed_qty=needed_qty)
        shipments_data.append({
            "shipment": s,
            "exchangeable_options": real_options,
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

    # 이미 기다리기(waiting=True) 또는 이미 changed_option이 설정되어 있으면 더 이상 수정 불가
    any_already = shipments.filter(
        Q(waiting=True) | ~Q(changed_option='')
    ).exists()
    if any_already:
        return HttpResponse("이미 처리된 내역(기다리기 or 옵션변경)이 존재하여 수정할 수 없습니다.", status=400)

    # 각 DelayedShipment에 대해 새 옵션/수량을 업데이트
    for s in shipments:
        new_opt_key = f"new_option_for_{s.id}"
        new_qty_key = f"new_qty_for_{s.id}"

        new_option = request.POST.get(new_opt_key, '')
        new_qty_str = request.POST.get(new_qty_key, '')

        try:
            new_qty = int(new_qty_str)
        except ValueError:
            new_qty = 1

        # 제한 로직: new_qty <= 기존 수량
        if new_qty > int(s.quantity or 1):
            messages.error(request, f"수량 {new_qty}는 현재 {s.quantity}을 초과할 수 없습니다.")
            return redirect(f"/delayed/option-change/?token={token}")

        # DB 업데이트
        s.changed_option = new_option
        s.quantity = new_qty
        s.confirmed = True     # 고객 확인 여부
        s.waiting = False      # 혹시 모를 값 초기화
        # ----> 새로 추가: 흐름 상태를 '확인완료'로 변경
        s.flow_status = 'confirmed'
        s.save()

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
            messages.success(request, f"{total_deleted}건이 삭제되었습니다.")
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
    출고완료 목록(shipped_list.html)에서:
      - action="complete_shipment" → 출고완료( flow_status='shipped' )
      - action="delete_multiple"   → 선택 삭제
    """
    if request.method == 'POST':
        action = request.POST.get('action', '')
        shipment_ids = request.POST.getlist('shipment_ids', [])

        if not shipment_ids:
            messages.warning(request, "선택된 항목이 없습니다.")
            return redirect('shipped_list')  # 출고완료 목록 페이지 (혹은 다른 페이지)

        qs = DelayedShipment.objects.filter(id__in=shipment_ids)

        if action == 'delete_multiple':
            deleted_info = qs.delete()
            total_deleted = deleted_info[0]
            messages.success(request, f"{total_deleted}건이 삭제되었습니다.")
            return redirect('shipped_list')

        elif action == 'complete_shipment':
            count = qs.update(flow_status='shipped')
            messages.success(request, f"{count}건 출고완료로 변경했습니다.")
            return redirect('shipped_list')

    # 그 외(GET 등) 잘못된 접근은 목록 페이지로
    return redirect('shipped_list')

def confirmed_list(request):
    """ 'confirmed' 인 애들만 (고객확인 완료) """
    qs = DelayedShipment.objects.filter(flow_status='confirmed').order_by('-created_at')
    return render(request, 'delayed_management/confirmed_list.html', {'shipments': qs})



