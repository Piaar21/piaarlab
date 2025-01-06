# return_process/views.py

from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
import requests
from django.shortcuts import render, redirect
from .models import ReturnItem, ScanLog
from .api_clients import (
    NAVER_ACCOUNTS,
    COUPANG_ACCOUNTS,
    fetch_naver_returns,
    fetch_coupang_returns,
    fetch_coupang_exchanges,
    get_seller_product_item_id,
    get_order_detail,
    get_external_vendor_sku,
    get_return_request_details,
    approve_naver_return,
    get_product_order_details,
    dispatch_naver_exchange
)
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from .forms import CustomUserCreationForm, ReturnItemForm  # 커스텀 유저 생성 폼
from .utils import save_return_items
import logging
from django.http import JsonResponse
from django.contrib import messages
from dateutil.parser import parse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
import json
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse
import openpyxl
from openpyxl import Workbook
import warnings
from django.db import transaction  # 이 부분을 추가
import datetime, uuid, hmac, hashlib, base64
from decouple import config
from django.conf import settings
from .utils import update_returns_logic
from django.db.models import Count



warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


logger = logging.getLogger(__name__)  # __name__은 현재 모듈 이름

class CustomLoginView(LoginView):
    template_name = 'return_process/login.html'
    success_url = reverse_lazy('반품목록')

class ReturnListView(LoginRequiredMixin, ListView):
    model = ReturnItem
    template_name = 'return_process/return_list.html'
    context_object_name = 'return_items'

@login_required
def return_list(request):
    status_map = {
        '미처리': '미처리',
        '스캔': '스캔',
        '수거완료': '수거완료',
        '검수완료': '검수완료',
        '반품완료': '반품완료',
        '재고반영': '재고반영',
        '처리완료': '처리완료'
    }

    # 최신 업데이트 기준으로 정렬된 아이템
    return_items = ReturnItem.objects.order_by('-last_update_date')
    # 총 반품건수
    total_count = return_items.count()

    # 상태별 카운트 (ORM 집계) - DB 상의 processing_status값 그대로 group by
    raw_status_counts = (
        return_items
        .values('processing_status')
        .annotate(count=Count('id'))
        .order_by('processing_status')
    )
    # raw_status_counts = [{'processing_status': '반품완료', 'count': 10}, ...]

    # 상태맵 사용해 사람이 읽기 좋은 상태명으로 교체
    # 예: DB에 '반품완료' 그대로 저장되어 있으면 그냥 동일, 
    #    만약 'returned' 같은 영어였다면 -> 한글 '반품완료'
    status_counts = []
    for sc in raw_status_counts:
        original_status = sc['processing_status']
        display_status = status_map.get(original_status, original_status)
        status_counts.append({
            'processing_status': display_status,
            'count': sc['count'],
        })

    return render(request, 'return_process/return_list.html', {
        'return_items': return_items,
        'total_count': total_count,
        'status_counts': status_counts,
    })


# 매핑 딕셔너리 상단에 위치 (기존 딕셔너리에 항목 추가)
receipt_type_map = {
    'RETURN': '반품',
    'CANCEL_REQUEST': '취소 요청',
    'RETURN_REQUEST': '반품 요청',
    'EXCHANGE_REQUEST': '교환 요청',
    'COMPENSATION_REQUEST': '보상 요청',
}

receipt_status_map = {
    'CANCEL_REQUEST': '취소 요청',
    'CANCEL_ACCEPT': '취소 수락',
    'CANCEL_REJECT': '취소 거부',
    'RETURNS_COMPLETED': '반품 완료',
    'RELEASE_STOP_UNCHECKED': '출고중지요청',
    'RETURNS_UNCHECKED': '반품접수',
    'VENDOR_WAREHOUSE_CONFIRM': '입고완료',
    'REQUEST_COUPANG_CHECK': '쿠팡확인요청',
    'RETURN_REQUEST': '반품 요청',
    'RETURN_ACCEPT': '반품 수락',
    'RETURN_REJECT': '반품 거부',
    'RETURN_COMPLETE': '반품 완료',
    'EXCHANGE_REQUEST': '교환 요청',
    'EXCHANGE_ACCEPT': '교환 수락',
    'EXCHANGE_REJECT': '교환 거부',
    'COLLECTING'	: '수거중',
    'COLLECT_DONE'    : '수거완료',
    'EXCHANGE_DONE	': '교환완료',
    'RETURN_REJECT	': '반품철회',
    'EXCHANGE_REJECT': '교환철회',
}

cancel_reason_category_map = {
    'CUSTOMER_CHANGE': '고객변심',
    'SELLER_FAULTY': '판매자 귀책',
    'DROPPED_DELIVERY': '배송 중 분실',
    'DAMAGED_DELIVERY': '배송 중 파손',
    'WRONG_DELIVERY': '오배송',  # 이미 여기에도 '오배송'이 있으나 상황에 따라 사용
    'PRODUCT_UNSATISFIED': '상품 불만족',
    'PRODUCT_DEFECT': '상품 불량',
}

status_code_mapping = {
    'WRONG_DELIVERED_PRODUCT': '오배송',
    'WRONG_PRODUCT_CONTENT': '상품 내용 불일치',
    'WRONG_DELAYED_DELIVERY': '배송 지연',
    'SIMPLE_INTENT_CHANGED': '단순 변심',
    'MISTAKE_ORDER': '주문 실수',
    'NO_LONGER_NEED_PRODUCT': '상품이 필요 없음',
    'PRODUCT_UNSATISFIED': '상품에 만족하지 않음',
    'PRODUCT_UNSATISFIED_COLOR': '색상 불만족',
    'PRODUCT_UNSATISFIED_SIZE': '사이즈 불만족',
    'BROKEN_AND_BAD': '상품 불량 및 파손',
    'PRODUCT_UNSATISFIED_ETC': '기타 불만족',
    'RETURN_REQUEST': '반품 요청',
    'RETURN_REJECT': '반품 철회',
    'RETURN_COMPLETED': '반품 완료',
    'EXCHANGE_REQUEST': '교환 요청',
    'EXCHANGE_REJECT': '교환 철회',
    'EXCHANGE_COMPLETED': '교환 완료',
    'COLLECT_WAITING': '회수 대기 중',
    'COLLECT_DONE': '회수 완료',
    'COLLECT_DELAYED': '회수 지연',
    'DELIVERED': '배송 완료',
    'DELIVERY_COMPLETION': '배송 완료',
    'DELIVERING': '배송 중',
    'SHIPPING': '배송 준비 중',
    'RETURN_DONE': '반품 완료',
    'PURCHASE_DECIDED': '구매 확정',

    # 추가한 매핑
    'COLOR_AND_SIZE': '색상 및 사이즈 변경',
    'WRONG_DELIVERY': '오배송',
}

product_order_status_map = {
    'PAYMENT_WAITING': '결제 대기',
    'PAYED': '결제 완료',
    'DELIVERING': '배송 중',
    'DELIVERED': '배송 완료',
    'PURCHASE_DECIDED': '구매 확정',
    'EXCHANGED': '교환완료',
    'CANCELED': '취소완료',
    'RETURNED': '반품완료',
    'CANCELED_BY_NOPAYMENT': '미결제 취소'
}


@login_required
def update_returns(request):
    update_returns_logic()
    messages.success(request, '반품 데이터 업데이트가 완료되었습니다.')
    return redirect('반품목록')


@login_required
def update_returns(request):
    update_returns_logic()
    messages.success(request, '반품 데이터 업데이트가 완료되었습니다.')
    return redirect('반품목록')

@login_required
def delete_return_item(request):
    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        item_ids = data.get('item_ids', [])

        if not item_ids:
            return JsonResponse({'success': False, 'message': '아이템 ID 목록이 필요합니다.'})

        deleted_count, _ = ReturnItem.objects.filter(id__in=item_ids).delete()
        if deleted_count > 0:
            return JsonResponse({'success': True, 'message': f'{deleted_count}개 항목 삭제 완료'})
        else:
            return JsonResponse({'success': False, 'message': '해당 ID의 레코드를 찾을 수 없습니다.'})
    else:
        return JsonResponse({'success': False, 'message': 'POST 요청만 가능합니다.'})


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

@login_required
def get_column_index_by_name(header_row, target_name):
    for idx, cell in enumerate(header_row):
        if cell.value and cell.value.strip() == target_name.strip():
            return idx
    return None


@login_required
def upload_returns_excel(request):
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            logger.warning("엑셀 파일이 선택되지 않았습니다.")
            return JsonResponse({'success': False, 'message': '엑셀 파일을 선택해주세요.'})
        
        try:
            wb = openpyxl.load_workbook(excel_file, data_only=True)
            logger.debug("셀러툴 엑셀 파일 로드 성공")
        except Exception as e:
            logger.error(f"엑셀 파일 로드 오류: {str(e)}")
            return JsonResponse({'success': False, 'message': '유효한 엑셀 파일이 아닙니다.'})

        ws = wb.active

        success_items = []
        error_items = []

        def format_korean_datetime(dt):
            if not dt:
                return ''
            formatted = dt.strftime("%Y년 %m월 %d일 %I:%M %p")
            formatted = formatted.replace("AM", "오전").replace("PM", "오후")
            logger.debug(f"format_korean_datetime: {dt} -> {formatted}")
            return formatted

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            values = [c.value for c in row]
            print(f"Row {row_idx} values: {values}")
            def cell_value(idx, is_numeric=False):
                if idx < len(row):
                    val = row[idx].value
                    if val is None:
                        return 0 if is_numeric else ''
                    if is_numeric:
                        return val if val != '' else 0
                    else:
                        return str(val).strip() if isinstance(val, str) else str(val)
                else:
                    return 0 if is_numeric else ''

            status = cell_value(0) or '미처리'
            claim_type = cell_value(1)
            store_name = cell_value(2)
            order_number = cell_value(3)
            collect_tracking_number = cell_value(4)
            collect_delivery_company = cell_value(5)
            recipient_name = cell_value(6)
            option_code = cell_value(7)
            product_name = cell_value(8)
            option_name = cell_value(9)
            quantity = cell_value(10, is_numeric=True)
            invoice_number = cell_value(11)
            # 하이픈 제거 추가
            invoice_number = invoice_number.replace('-', '') if invoice_number else invoice_number

            claim_status = cell_value(12)
            claim_reason = cell_value(13)
            customer_reason = cell_value(14)
            return_shipping_charge = cell_value(15, is_numeric=True)
            shipping_charge_payment_method = cell_value(16)
            processing_status = cell_value(17) or '미처리'
            note = cell_value(18)
            inspector = cell_value(19)
            product_issue = cell_value(20)
            raw_delivered_date = cell_value(21)
            raw_claim_request_date = cell_value(22)

            logger.debug(f"[Row {row_idx}] order_number={order_number}, raw_delivered_date={raw_delivered_date}, raw_claim_request_date={raw_claim_request_date}")

            if not order_number:
                error_items.append({
                    'row': row_idx,
                    'reason': '주문번호 없음'
                })
                continue

            # 스토어명 매핑
            store_name_map = {
                "노는 개 최고양": "노는개최고양",
                "수비다 SUBIDA": "수비다"
            }
            if store_name in store_name_map:
                store_name = store_name_map[store_name]

            # 특정 스토어일 경우 platform='Naver' 설정
            naver_stores = ["니뜰리히", "노는개최고양", "아르빙", "수비다"]
            # store_name이 매핑된 후의 값으로 확인
            # 예: "노는 개 최고양" -> "노는개최고양" 후에 체크
            if store_name in naver_stores:
                platform_val = 'Naver'
            else:
                platform_val = ''  # 혹은 필요하다면 다른 값

            # 기존에 platform='Naver'로 제한했던 get_or_create 제거
            item, created = ReturnItem.objects.get_or_create(
                order_number=order_number,
                option_code=option_code
            )
            
            # platform 설정
            item.platform = platform_val

            item.processing_status = processing_status
            item.claim_type = claim_type
            item.store_name = store_name
            item.collect_tracking_number = collect_tracking_number
            item.collect_delivery_company = collect_delivery_company
            item.recipient_name = recipient_name
            item.option_code = option_code
            item.product_name = product_name
            item.option_name = option_name
            item.quantity = quantity
            item.invoice_number = invoice_number
            item.claim_status = claim_status
            item.claim_reason = claim_reason
            item.customer_reason = customer_reason
            item.return_shipping_charge = return_shipping_charge
            item.shipping_charge_payment_method = shipping_charge_payment_method
            item.note = note
            item.inspector = inspector
            item.product_issue = product_issue

            def parse_date(raw_val):
                if raw_val == '':
                    logger.debug(f"parse_date: empty string -> None")
                    return None
                try:
                    logger.debug(f"parse_date: attempting to parse {raw_val}")
                    # raw_val이 "YYYY-MM-DD" 형태로 들어온다고 가정
                    parsed = datetime.datetime.strptime(raw_val, "%Y-%m-%d")
                    parsed = parsed.replace(hour=10, minute=0)
                    logger.debug(f"parse_date: {raw_val} -> {parsed}")
                    return parsed
                except ValueError as ve:
                    logger.warning(f"parse_date: {raw_val} 변환 실패: {ve}")
                    return None

            delivered_date = parse_date(raw_delivered_date)
            claim_request_date = parse_date(raw_claim_request_date)

            logger.debug(f"[Row {row_idx}] 파싱 결과 delivered_date={delivered_date}, claim_request_date={claim_request_date}")

            item.delivered_date = delivered_date
            item.claim_request_date = claim_request_date
            item.save()

            # 날짜 포맷 변환
            formatted_delivered = format_korean_datetime(item.delivered_date)
            formatted_claim_request = format_korean_datetime(item.claim_request_date)
            logger.debug(f"[Row {row_idx}] formatted_delivered={formatted_delivered}, formatted_claim_request={formatted_claim_request}")

            success_items.append({
                'order_number': item.order_number,
                'display_status': getattr(item, 'display_status', ''), # display_status 필드가 없을 수 있으니 getattr 사용
                'claim_type': item.claim_type,
                'store_name': item.store_name,
                'collect_tracking_number': item.collect_tracking_number,
                'collect_delivery_company': item.collect_delivery_company,
                'recipient_name': item.recipient_name,
                'option_code': item.option_code,
                'product_name': item.product_name,
                'option_name': item.option_name,
                'quantity': item.quantity,
                'invoice_number': item.invoice_number,
                'claim_status': item.claim_status,
                'claim_reason': item.claim_reason,
                'customer_reason': item.customer_reason,
                'return_shipping_charge': item.return_shipping_charge,
                'shipping_charge_payment_method': item.shipping_charge_payment_method,
                'processing_status': item.processing_status,
                'note': item.note,
                'inspector': item.inspector,
                'product_issue': item.product_issue,
                'delivered_date': formatted_delivered,
                'claim_request_date': formatted_claim_request,
                'display_status': getattr(item, 'display_status', ''),
            })

        logger.debug(f"업로드 완료: 성공={len(success_items)}개, 실패={len(error_items)}개")

        # 업로드한 데이터 '미처리' 상태로 업데이트
        uploaded_order_numbers = [item['order_number'] for item in success_items]
        ReturnItem.objects.filter(order_number__in=uploaded_order_numbers).update(processing_status='미처리')

        return JsonResponse({
            'success': True,
            'items': success_items,
            'errors': error_items
        })
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def upload_courier_excel(request):
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            logger.warning("엑셀 파일이 선택되지 않았습니다.")
            return JsonResponse({'success': False, 'message': '엑셀 파일을 선택해주세요.'})

        try:
            wb = openpyxl.load_workbook(excel_file, data_only=True)
            logger.debug("택배사 엑셀 파일 로드 성공")
        except Exception as e:
            logger.error(f"엑셀 파일 로드 오류: {str(e)}")
            return JsonResponse({'success': False, 'message': '유효한 엑셀 파일이 아닙니다.'})

        ws = wb.active

        header = next(ws.iter_rows(min_row=1, max_row=1))
        header_values = [cell.value for cell in header]
        logger.debug(f"택배사 엑셀 헤더: {header_values}")

        related_col_name = "관련운송장"
        new_collect_col_name = "운송장번호"
        delivered_date_col_name = "배송일자"  # 실제 헤더명에 맞게 변경 필요

        def get_col_index(col_name):
            if col_name in header_values:
                return header_values.index(col_name)
            else:
                raise Exception(f"'{col_name}' 컬럼을 찾을 수 없습니다. 엑셀 헤더를 확인하세요.")

        try:
            related_waybill_col = get_col_index(related_col_name)
            new_collect_col = get_col_index(new_collect_col_name)
            delivered_date_col = get_col_index(delivered_date_col_name)
        except Exception as e:
            logger.error(str(e))
            return JsonResponse({'success': False, 'message': str(e)})

        success_items = []
        error_items = []

        def parse_date(val):
            # val이 datetime.datetime 인스턴스인지 체크
            if isinstance(val, datetime.datetime):
                logger.debug(f"parse_date: {val}는 datetime 객체입니다.")
                parsed = val.replace(hour=10, minute=0)  # 예: 10:00으로 설정
                logger.debug(f"parse_date: 시간 설정 후 {parsed}")
                return parsed
            # 문자열인 경우
            if isinstance(val, str) and val.strip():
                logger.debug(f"parse_date: '{val}' 문자열 파싱 시도")
                try:
                    # "YYYY-MM-DD" 형식 가정
                    parsed = datetime.datetime.strptime(val.strip(), "%Y-%m-%d")
                    parsed = parsed.replace(hour=10, minute=0)
                    logger.debug(f"parse_date: {val} -> {parsed}")
                    return parsed
                except ValueError as ve:
                    logger.warning(f"parse_date: '{val}' 변환 실패: {ve}")
                    return None
            logger.debug(f"parse_date: '{val}'는 빈 값 또는 알 수 없는 형식")
            return None

        def format_korean_datetime(dt):
            if not dt:
                return ''
            formatted = dt.strftime("%Y년 %m월 %d일 %I:%M %p")
            formatted = formatted.replace("AM", "오전").replace("PM", "오후")
            logger.debug(f"format_korean_datetime: {dt} -> {formatted}")
            return formatted

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
            raw_related = row[related_waybill_col].value
            raw_collect_tracking = row[new_collect_col].value
            raw_delivered_date = row[delivered_date_col].value

            logger.debug(f"[Row {row_idx}] raw_related={raw_related}, raw_collect_tracking={raw_collect_tracking}, raw_delivered_date={raw_delivered_date}")

            # 관련운송장 변환
            if isinstance(raw_related, datetime.datetime):
                related_waybill = raw_related.strftime("%Y%m%d%H%M%S")
            else:
                related_waybill = str(raw_related).strip() if raw_related else None

            # 수거송장번호 변환
            if isinstance(raw_collect_tracking, datetime.datetime):
                new_collect_tracking = raw_collect_tracking.strftime("%Y%m%d%H%M%S")
            else:
                new_collect_tracking = str(raw_collect_tracking).strip() if raw_collect_tracking else None

            # "-" 문자 제거
            if related_waybill:
                related_waybill = related_waybill.replace("-", "")
            if new_collect_tracking:
                new_collect_tracking = new_collect_tracking.replace("-", "")

            logger.debug(f"[Row {row_idx}] 배송일자 파싱 시작: {raw_delivered_date}")
            courier_delivered_date = parse_date(raw_delivered_date)
            logger.debug(f"[Row {row_idx}] 파싱 결과 courier_delivered_date={courier_delivered_date}")

            if not related_waybill:
                logger.debug(f"[Row {row_idx}] 관련운송장 없음. 스킵.")
                continue

            items = ReturnItem.objects.filter(invoice_number=related_waybill)

            if not items.exists():
                logger.warning(f"[Row {row_idx}] invoice_number={related_waybill} 매칭 데이터 없음.")
                error_items.append({
                    'row': row_idx,
                    'related_waybill': related_waybill,
                    'error': '매칭되는 데이터 없음'
                })
                continue

            logger.debug(f"[Row {row_idx}] {items.count()}개 항목 매칭됨.")

            for item in items:
                original_collect = item.collect_tracking_number
                original_delivered = item.delivered_date

                if new_collect_tracking:
                    item.collect_tracking_number = new_collect_tracking
                if courier_delivered_date:
                    item.delivered_date = courier_delivered_date

                item.save()

                logger.debug(f"[Row {row_idx}] 주문번호={item.order_number}, CollectTracking: {original_collect} -> {item.collect_tracking_number}, DeliveredDate: {original_delivered} -> {item.delivered_date}")

                formatted_delivered = format_korean_datetime(item.delivered_date)

                logger.debug(f"[Row {row_idx}] formatted_delivered={formatted_delivered}")

                success_items.append({
                    'order_number': item.order_number,
                    'display_status': item.display_status,
                    'claim_type': item.claim_type,
                    'store_name': item.store_name,
                    'collect_tracking_number': item.collect_tracking_number or '',
                    'collect_delivery_company': item.collect_delivery_company or '',
                    'recipient_name': item.recipient_name or '',
                    'option_code': item.option_code or '',
                    'product_name': item.product_name or '',
                    'option_name': item.option_name or '',
                    'quantity': item.quantity,
                    'invoice_number': item.invoice_number or '',
                    'claim_status': item.claim_status or '',
                    'claim_reason': item.claim_reason or '',
                    'customer_reason': item.customer_reason or '',
                    'return_shipping_charge': item.return_shipping_charge or '',
                    'shipping_charge_payment_method': item.shipping_charge_payment_method or '',
                    'processing_status': item.processing_status or '',
                    'note': item.note or '',
                    'inspector': item.inspector or '',
                    'product_issue': item.product_issue or '',
                    'delivered_date': formatted_delivered,
                    'claim_request_date': item.claim_request_date.isoformat() if item.claim_request_date else '',
                    'display_status': item.display_status
                })

        logger.debug(f"업로드 완료: 성공={len(success_items)}개, 실패={len(error_items)}개")
        return JsonResponse({'success': True, 'items': success_items, 'errors': error_items})

    return JsonResponse({'success': False, 'message': 'Invalid request'})


@login_required
def finalize_excel_import(request):
    """
    여기서 더 이상 모든 데이터를 '미처리'로 업데이트하지 않습니다.
    즉, 기존 데이터 상태를 손상시키지 않고,
    단지 업로드한 데이터가 반품목록에 반영되도록 하려면
    사실상 이 함수에서 할 작업이 없거나 최소화해야 합니다.
    """

    # 필요하다면 특정 조건으로 필터링하여 방금 업로드한 데이터만 상태 변경 가능
    # 예: ReturnItem.objects.filter(...).update(processing_status='미처리')
    # 하지만 문제를 피하기 위해 아무것도 하지 않고 바로 반품목록 페이지로 이동
    messages.success(request, '엑셀 업로드 데이터가 반품목록에 반영되었습니다.')
    return redirect('반품목록')



# views.py 변경 없음 (단, 날짜 파싱 부분 수정)
@csrf_exempt
def upload_reason_excel(request):
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            return JsonResponse({'success': False, 'message': '엑셀 파일을 선택해주세요.'})

        try:
            wb = openpyxl.load_workbook(excel_file, data_only=True)
        except Exception as e:
            return JsonResponse({'success': False, 'message': '유효한 엑셀 파일이 아닙니다.'})

        ws = wb.active

        # 헤더 매핑:
        # R(18), D(4), E(5), F(6), K(11)
        claim_status_col = 4
        claim_reason_col = 5
        customer_reason_col = 6
        claim_request_col = 11
        order_number_col = 18

        success_items = []
        error_items = []

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            order_number = row[order_number_col - 1]
            claim_status = row[claim_status_col - 1]
            claim_reason = row[claim_reason_col - 1]
            customer_reason = row[customer_reason_col - 1]
            claim_request_raw = row[claim_request_col - 1]

            # 기존 코드에서 날짜 파싱 부분 수정
            if isinstance(claim_request_raw, datetime.datetime):
                claim_request_date = claim_request_raw
            elif isinstance(claim_request_raw, str) and claim_request_raw.strip():
                raw_str = claim_request_raw.strip()
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                    try:
                        claim_request_date = datetime.datetime.strptime(raw_str, fmt)
                        break
                    except ValueError:
                        continue

            # 날짜를 한국어 포맷으로 변환
            if claim_request_date:
                claim_request_date_str = claim_request_date.strftime("%Y년 %m월 %d일 %I:%M %p")
                claim_request_date_str = claim_request_date_str.replace("AM", "오전").replace("PM", "오후")
            else:
                claim_request_date_str = None

            if not order_number:
                error_items.append({
                    'row': row_idx,
                    'error': '주문번호(R열) 없음'
                })
                continue

            items = ReturnItem.objects.filter(order_number=order_number)
            if not items.exists():
                error_items.append({
                    'row': row_idx,
                    'order_number': order_number,
                    'error': '매칭되는 주문번호 없음'
                })
                continue

            for item in items:
                item.claim_status = claim_status if claim_status else item.claim_status
                item.claim_reason = claim_reason if claim_reason else item.claim_reason
                item.customer_reason = customer_reason if customer_reason else item.customer_reason
                if claim_request_date:
                    item.claim_request_date = claim_request_date
                item.save()

                success_items.append({
                    'order_number': item.order_number,
                    'display_status': item.display_status,
                    'claim_type': item.claim_type,
                    'store_name': item.store_name,
                    'collect_tracking_number': item.collect_tracking_number or '',
                    'collect_delivery_company': item.collect_delivery_company or '',
                    'recipient_name': item.recipient_name or '',
                    'option_code': item.option_code or '',
                    'product_name': item.product_name or '',
                    'option_name': item.option_name or '',
                    'quantity': item.quantity,
                    'invoice_number': item.invoice_number or '',
                    'claim_status': item.claim_status or '',
                    'claim_reason': item.claim_reason or '',
                    'customer_reason': item.customer_reason or '',
                    'return_shipping_charge': item.return_shipping_charge or '',
                    'shipping_charge_payment_method': item.shipping_charge_payment_method or '',
                    'processing_status': item.processing_status or '',
                    'note': item.note or '',
                    'inspector': item.inspector or '',
                    'product_issue': item.product_issue or '',
                    'delivered_date': item.delivered_date.isoformat() if item.delivered_date else '',
                    'claim_request_date': item.claim_request_date.isoformat() if item.claim_request_date else '',
                    'display_status': item.display_status
                })

        return JsonResponse({'success': True, 'items': success_items, 'errors': error_items})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})



@login_required
def scan(request):
    # DB에서 로그인한 사용자(user=request.user)가 등록한 스캔 목록 읽어오기
    scanned_qs = ScanLog.objects.filter(user=request.user, matched=True).order_by('created_at')
    unmatched_qs = ScanLog.objects.filter(user=request.user, matched=False).order_by('created_at')

    # 템플릿에 넘길 리스트
    scanned_numbers = [obj.tracking_number for obj in scanned_qs]
    unmatched_numbers = [obj.tracking_number for obj in unmatched_qs]

    if request.method == 'POST':
        remove_number = request.POST.get('remove_number')
        if remove_number:
            # scanned
            removed = ScanLog.objects.filter(user=request.user,
                                             tracking_number=remove_number).delete()
            if removed[0] > 0:
                messages.success(request, f"{remove_number} 운송장번호를 제거했습니다.")
            else:
                messages.warning(request, f"{remove_number} 운송장번호를 찾을 수 없습니다.")

    return render(request, 'return_process/scan.html', {
        'scanned_numbers': scanned_numbers,
        'unmatched_numbers': unmatched_numbers,
    })


@csrf_exempt
def scan_submit(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError:
            data = request.POST.dict()

        action = data.get('action', None)
        scanned_numbers = request.session.get('scanned_numbers', [])
        unmatched_numbers = request.session.get('unmatched_numbers', [])
        user = request.user

        if not action:
            return JsonResponse({'success': False, 'error': 'action parameter is missing'})

        # # 기존 로직
        # print("DEBUG: action value:", action, flush=True)
        # if action == 'check_number':
        #     number = data.get('number', '').strip()
        #     print("DEBUG: check_number received:", repr(number), flush=True)
            
        #     if not number:
        #         return JsonResponse({'success': False, 'error': 'no number provided', 'action': 'check_number'})

        #     exists = ReturnItem.objects.filter(collect_tracking_number=number).exists()
        #     if exists:
        #         if number not in scanned_numbers and number not in unmatched_numbers:
        #             scanned_numbers.append(number)
        #             request.session['scanned_numbers'] = scanned_numbers
        #         return JsonResponse({'success': True, 'matched': True, 'number': number, 'action': 'check_number'})
        #     else:
        #         if number not in unmatched_numbers and number not in scanned_numbers:
        #             unmatched_numbers.append(number)
        #             request.session['unmatched_numbers'] = unmatched_numbers
        #         return JsonResponse({'success': True, 'matched': False, 'number': number, 'action': 'check_number'})

        if action == 'approve_returns':
            # 1) DB에서 user가 matched=True로 저장해둔 운송장번호 목록을 가져옴
            matched_logs = ScanLog.objects.filter(user=user, matched=True)
            scanned_numbers = [log.tracking_number for log in matched_logs]

            # 디버깅용
            print("DEBUG: scanned_numbers at approve_returns:", scanned_numbers)

            if scanned_numbers:
                # 2) 실제 DB에 존재하는 ReturnItem만 필터
                existing_items = ReturnItem.objects.filter(collect_tracking_number__in=scanned_numbers)
                existing_numbers = list(existing_items.values_list('collect_tracking_number', flat=True))
                print("DEBUG: existing_numbers found in DB:", existing_numbers)

                # 3) new_unmatched: 스캔은 했지만 ReturnItem에 없는 번호
                scanned_set = set(scanned_numbers)
                existing_set = set(existing_numbers)
                new_unmatched = list(scanned_set - existing_set)

                # 4) 실제 존재하는 아이템은 수거완료 처리(원하면 '검수완료'로 변경)
                items = ReturnItem.objects.filter(collect_tracking_number__in=existing_numbers)

                for item in items:
                    item.processing_status = '수거완료'
                    item.save()  # 오버라이드된 save() 메서드 실행 -> collected_at 자동 기록
                # 5) matched_logs 전부 삭제 (혹은 남겨두고 싶다면 다른 로직)
                matched_logs.delete()

                # 6) new_unmatched를 DB에 저장(미일치)하거나 로그 업데이트
                #    기존 미일치 로그로 만들기
                for num in new_unmatched:
                    # 이미 unmatched=True로 등록된게 없으면 생성
                    obj, created = ScanLog.objects.get_or_create(user=user, tracking_number=num)
                    if obj.matched:  # 만약 기존이 matched였다면
                        obj.matched = False
                        obj.save()

                if new_unmatched:
                    return JsonResponse({
                        'success': True,
                        'message': '전송 완료하였으나 일부 일치하지 않는 송장이 있습니다.',
                        'unmatched_numbers': new_unmatched
                    })
                else:
                    return JsonResponse({'success': True, 'message': '전송되었습니다.'})
            else:
                return JsonResponse({'success': False, 'message': '스캔한 운송장번호가 없습니다.'})

        elif action == 'recheck_unmatched':
            # 1) DB에서 user가 matched=False인 운송장번호를 확인
            unmatched_logs = ScanLog.objects.filter(user=user, matched=False)
            unmatched_numbers = [log.tracking_number for log in unmatched_logs]

            if unmatched_numbers:
                # 2) 실제 존재하는 ReturnItem
                existing_items = ReturnItem.objects.filter(collect_tracking_number__in=unmatched_numbers)
                existing_numbers = set(existing_items.values_list('collect_tracking_number', flat=True))

                re_matched = []
                for log in unmatched_logs:
                    if log.tracking_number in existing_numbers:
                        log.matched = True
                        log.save()
                        re_matched.append(log.tracking_number)

                if re_matched:
                    return JsonResponse({
                        'success': True,
                        'message': f"일치하지 않던 {len(re_matched)}건의 송장이 다시 확인되어 일치하는 목록으로 이동했습니다."
                    })
                else:
                    return JsonResponse({'success': True, 'message': '일치하는 송장이 없습니다.'})
            else:
                return JsonResponse({'success': True, 'message': '미일치 목록이 비어있습니다.'})

        # 여기서부터 새로운 액션 처리 로직 추가
        elif action == 'update_issue':
            ids = data.get('ids', [])
            product_issue = data.get('product_issue', '').strip()

            if not ids:
                return JsonResponse({'success': False, 'message': 'No item ids provided.'})

            # 1) 해당 아이템들 가져오기
            items = ReturnItem.objects.filter(id__in=ids)

            # 업데이트된 갯수를 세기 위해 변수 준비
            #  - 방법 A) items를 순회하며 count += 1
            #  - 방법 B) save() 끝난 뒤 len(items)를 그대로 사용
            updated_count = len(items)

            # 2) 개별 아이템에 대해 product_issue, processing_status 설정 + save()
            for item in items:
                item.product_issue = product_issue
                item.processing_status = '검수완료'
                item.save()

            # 3) updated_count에 따라 응답
            if updated_count > 0:
                return JsonResponse({'success': True, 'updated_count': updated_count})
            else:
                return JsonResponse({'success': False, 'message': 'No items updated.'})

        elif action == 'update_note':
            ids = data.get('ids', [])
            note = data.get('note', '').strip()
            if not ids:
                return JsonResponse({'success': False, 'message': 'No item ids provided.'})

            updated_count = ReturnItem.objects.filter(id__in=ids).update(note=note)
            if updated_count > 0:
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'message': 'No items updated.'})
        
        elif action == 'delete_items':
            ids = data.get('ids', [])
            ReturnItem.objects.filter(id__in=ids).delete()
            return JsonResponse({'success': True})

        elif action == 'update_quantity':
            item_id = data.get('id', None)
            new_quantity = data.get('new_quantity', None)
            if item_id and new_quantity is not None:
                try:
                    item = ReturnItem.objects.get(id=item_id)
                    item.quantity = new_quantity
                    item.save()
                    return JsonResponse({'success': True})
                except ReturnItem.DoesNotExist:
                    return JsonResponse({'success': False, 'message': 'Item not found'})
            else:
                return JsonResponse({'success': False, 'message': 'Invalid parameters'})
        elif action == 'get_details':
            item_id = data.get('id', None)
            if not item_id:
                return JsonResponse({'success': False, 'message': 'No item id provided.'})
            try:
                item = ReturnItem.objects.get(id=item_id)
                details = {
                    'order_number': item.order_number,
                    'display_status': item.display_status,
                    'claim_type': item.claim_type,
                    'store_name': item.store_name,
                    'collect_tracking_number': item.collect_tracking_number,
                    'collect_delivery_company': item.collect_delivery_company,
                    'recipient_name': item.recipient_name,
                    'option_code': item.option_code,
                    'product_name': item.product_name,
                    'option_name': item.option_name,
                    'quantity': item.quantity,
                    'invoice_number': item.invoice_number,
                    'claim_status': item.claim_status,
                    'claim_reason': item.claim_reason,
                    'customer_reason': item.customer_reason,
                    'return_shipping_charge': item.return_shipping_charge,
                    'shipping_charge_payment_method': item.shipping_charge_payment_method,
                    'processing_status': item.processing_status,
                    'note': item.note,
                    'inspector': item.inspector,
                    'product_issue': item.product_issue,
                    'delivered_date': item.delivered_date.isoformat() if item.delivered_date else '',
                    'claim_request_date': item.claim_request_date.isoformat() if item.claim_request_date else '',
                }
                return JsonResponse({'success': True, 'details': details})
            except ReturnItem.DoesNotExist:
                return JsonResponse({'success': False, 'message': 'Item not found.'})
        
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@csrf_exempt
@login_required
def check_number_submit(request):
    """
    스캔된 운송장번호 목록을 DB(ScanLog, ReturnItem)로 관리하는 예시.
    스캔 시점에:
      1) collect_tracking_number가 존재하면 ReturnItem의 상태를 '검수완료'(또는 '수거완료')로 변경
      2) ScanLog에 matched=True로 등록
    존재하지 않으면 matched=False로 등록
    """
    if request.method == 'POST':
        user = request.user
        data = json.loads(request.body.decode('utf-8'))
        numbers = data.get('numbers', [])

        # 이미 DB에 저장된 스캔 정보 읽어오기
        existing_scanned = set(
            ScanLog.objects.filter(user=user, matched=True)
                           .values_list('tracking_number', flat=True)
        )
        existing_unmatched = set(
            ScanLog.objects.filter(user=user, matched=False)
                           .values_list('tracking_number', flat=True)
        )

        matched_list = []
        unmatched_list = []

        for num in numbers:
            number = num.strip()
            if not number:
                continue  # 공백만 있는 경우 건너뜀

            # 실제로 ReturnItem(collect_tracking_number=number) 존재 여부 체크
            item_qs = ReturnItem.objects.filter(collect_tracking_number=number)
            exists = item_qs.exists()
            if exists:

                item_qs.update(processing_status='검수완료')

                # ====== ScanLog 등록 (matched=True) ======
                if number not in existing_scanned and number not in existing_unmatched:
                    ScanLog.objects.create(
                        user=user,
                        tracking_number=number,
                        matched=True
                    )
                    existing_scanned.add(number)

                matched_list.append(number)

            else:
                # ====== DB에 없음 → 미일치 처리 ======
                if number not in existing_scanned and number not in existing_unmatched:
                    ScanLog.objects.create(
                        user=user,
                        tracking_number=number,
                        matched=False
                    )
                    existing_unmatched.add(number)

                unmatched_list.append(number)

        return JsonResponse({
            'success': True,
            'matched_list': matched_list,
            'unmatched_list': unmatched_list
        })

    else:
        return JsonResponse({'success': False, 'message': 'Only POST allowed'}, status=405)   
            
@login_required
def download_unmatched(request):
    unmatched_logs = ScanLog.objects.filter(user=request.user, matched=False)
    # 미일치 리스트를 엑셀로 다운로드
    unmatched_numbers = [log.tracking_number for log in unmatched_logs]

    wb = Workbook()
    ws = wb.active
    ws.title = "Unmatched"

    # 헤더


    row = 1
    for num in unmatched_numbers:
        ws.cell(row=row, column=1, value=num)
        row += 1

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="unmatched_numbers.xlsx"'
    wb.save(response)
    return response

@login_required
def collected_items(request):
    items = ReturnItem.objects.filter(processing_status='수거완료')

    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        action = data.get('action')

        if action == 'update_all_claim_status':
            order_numbers = list(items.values_list('order_number', flat=True))

            if not items.exists():
                return JsonResponse({'success': False, 'message': '수거완료 상태인 아이템이 없습니다.'}, status=400)

            # 첫 번째 아이템 기준으로 account_info 결정 (예시)
            first_item = items.first()
            platform = first_item.platform.lower()
            store_name = first_item.store_name
            if platform == 'naver':
                target_account = next((acc for acc in NAVER_ACCOUNTS if store_name in acc['names']), None)
                if not target_account:
                    return JsonResponse({'success': False, 'message': 'NAVER 계정을 찾을 수 없음'}, status=400)
                account_info = target_account
            else:
                return JsonResponse({'success': False, 'message': '지원되지 않는 플랫폼'}, status=400)

            MAX_IDS = 50  # API 제한을 고려한 최대 갯수
            chunked_details = []

            for i in range(0, len(order_numbers), MAX_IDS):
                batch = order_numbers[i:i+MAX_IDS]
                batch_result = get_product_order_details(account_info, batch)
                if not batch_result.get('success'):
                    return JsonResponse({'success': False, 'message': batch_result.get('message')}, status=400)
                chunked_details.extend(batch_result.get('details', []))

            updated_count = 0
            for detail in chunked_details:
                order_id = detail.get('productOrderId')
                status = detail.get('productOrderStatus', 'N/A')
                item = ReturnItem.objects.filter(order_number=order_id, processing_status='수거완료').first()
                if item:
                    item.product_order_status = status
                    item.save()
                    updated_count += 1

            return JsonResponse({'success': True, 'updated_count': updated_count})

    return render(request, 'return_process/collected_items.html', {'items': items})

@login_required
def inspect(request, item_id):
    item = ReturnItem.objects.get(id=item_id)
    if request.method == 'POST':
        inspection_result = request.POST.get('inspection_result')
        
        # inspection_result는 '오배송', '이상없음', '파손 및 불량' 중 하나라고 가정
        # product_issue 필드에 해당 값을 그대로 저장 가능
        item.product_issue = inspection_result

        # 검수 완료 시 processing_status를 '검수완료'로 업데이트
        item.processing_status = '검수완료'

        # 검수자 이름을 추가하고 싶다면 inspector 필드에도 저장 가능
        # item.inspector = request.user.username 등 필요한 값 설정
        
        item.save()
        return redirect('검수완료')  # 'inspected_items' 뷰의 URL name

    return render(request, 'return_process/inspect.html', {'item': item})

@login_required
def inspected_items(request):
    items = ReturnItem.objects.filter(processing_status='검수완료')

    if request.method == 'POST':
        data = json.loads(request.body.decode('utf-8'))
        action = data.get('action', None)  # <-- 안전하게 선언

        if action == 'update_all_claim_status':
            # --- 기존 코드 (수정 불가) ---
            if not items.exists():
                return JsonResponse({'success': False, 'message': '검수완료 상태인 아이템이 없습니다.'}, status=400)

            from collections import defaultdict
            grouped_by_account = defaultdict(list)
            for item in items:
                platform = item.platform.lower()
                store_name = item.store_name
                if platform == 'naver':
                    target_account = next((acc for acc in NAVER_ACCOUNTS if store_name in acc['names']), None)
                    if not target_account:
                        continue
                    account_key = (platform, store_name)
                    grouped_by_account[account_key].append(item.order_number)
                else:
                    pass

            MAX_IDS = 50
            total_updated_count = 0

            for (platform, store_name), order_numbers in grouped_by_account.items():
                account_info = next((acc for acc in NAVER_ACCOUNTS if store_name in acc['names']), None)
                if not account_info:
                    continue

                chunked_details = []
                for i in range(0, len(order_numbers), MAX_IDS):
                    batch = order_numbers[i:i+MAX_IDS]
                    batch_result = get_product_order_details(account_info, batch)
                    if not batch_result.get('success'):
                        return JsonResponse({'success': False, 'message': batch_result.get('message')}, status=400)
                    chunked_details.extend(batch_result.get('details', []))

                for detail in chunked_details:
                    order_id = detail.get('productOrderId')
                    status = detail.get('productOrderStatus', 'N/A')
                    item = ReturnItem.objects.filter(order_number=order_id, processing_status='검수완료').first()
                    if item:
                        item.product_order_status = status
                        item.save()
                        total_updated_count += 1

            return JsonResponse({'success': True, 'updated_count': total_updated_count})
        elif action == 'back_to_collected':
            ids = data.get('ids', [])
            ReturnItem.objects.filter(id__in=ids, processing_status='검수완료').update(processing_status='수거완료')
            return JsonResponse({'success': True})
        
        elif action == 'dispatch_exchange':
            print("[DEBUG] dispatch_exchange action 호출됨.")
            print(f"[DEBUG] request.POST or body data: {data}")

            product_order_id = data.get('product_order_id')
            re_delivery_method = data.get('re_delivery_method', 'DELIVERY')
            re_delivery_company = data.get('re_delivery_company') or None
            re_delivery_tracking_number = data.get('re_delivery_tracking_number') or None

            print(f"[DEBUG] 전달받은 product_order_id={product_order_id}, "
                  f"re_delivery_method={re_delivery_method}, "
                  f"re_delivery_company={re_delivery_company}, "
                  f"re_delivery_tracking_number={re_delivery_tracking_number}")

            # 디버깅: DB에 어떤 레코드가 있는지 한번 출력해보기
            count_all = ReturnItem.objects.filter(order_number=product_order_id).count()
            count_in_inspected = ReturnItem.objects.filter(order_number=product_order_id, processing_status='검수완료').count()
            print(f"[DEBUG] order_number={product_order_id} 전체 매칭 개수: {count_all}")
            print(f"[DEBUG] order_number={product_order_id} + 검수완료 매칭 개수: {count_in_inspected}")

            # item 조회
            item = ReturnItem.objects.filter(order_number=product_order_id, processing_status='검수완료').first()
            if not item:
                print("[DEBUG] 400 반환: 해당 주문번호(검수완료) 아이템을 찾을 수 없습니다.")
                return JsonResponse({'success': False, 'message': '해당 주문번호(검수완료) 아이템을 찾을 수 없습니다.'}, status=400)

            # >>> 여기서 실제 DB에서 찾은 item의 order_number를 찍어볼 수 있음 <<<
            print(f"[DEBUG] 찾은 item: ID={item.id}, order_number={item.order_number}")

            platform = item.platform.lower()
            print(f"[DEBUG] 찾은 item의 platform={platform}, store_name={item.store_name}")

            if platform != 'naver':
                print(f"[DEBUG] 400 반환: 네이버가 아닌 플랫폼({platform})")
                return JsonResponse({'success': False, 'message': f'네이버 플랫폼이 아니므로 재배송 처리를 지원하지 않습니다. ({platform})'}, status=400)

            store_name = item.store_name
            account_info = next((acc for acc in NAVER_ACCOUNTS if store_name in acc['names']), None)
            if not account_info:
                print("[DEBUG] 400 반환: NAVER 계정을 찾을 수 없음")
                return JsonResponse({'success': False, 'message': 'NAVER 계정을 찾을 수 없음'}, status=400)

            # 여기서 dispatch_naver_exchange 함수 콜
            success, message = dispatch_naver_exchange(
                account_info=account_info,
                product_order_id=product_order_id,
                re_delivery_method=re_delivery_method,
                re_delivery_company=re_delivery_company,
                re_delivery_tracking_number=re_delivery_tracking_number
            )

            print(f"[DEBUG] 교환 재배송 처리 결과: success={success}, message={message}")
            return JsonResponse({'success': success, 'message': message})

    # 기존 GET 로직 그대로
    return render(request, 'return_process/inspected_items.html', {'items': items})



@csrf_exempt
def send_shipping_sms(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        items = data.get('items', [])

        account = settings.SOLAPI_ACCOUNTS[0]
        api_key = account['api_key']
        api_secret = account['api_secret']
        sender = account['sender']

        url = "https://api.solapi.com/messages/v4/send-many"

        # 메시지 목록 구성
        message_list = []
        for item in items:
            recipient_contact = item['recipient_contact']
            store_name = item['store_name']
            return_shipping_charge = item['return_shipping_charge']

            text = f"""[반품 배송비 송금 안내드립니다]

안녕하세요, {store_name}입니다.
먼저 저희 제품을 이용해주셔서 진심으로 감사드리며, 반품 관련하여 안내드립니다.

고객님께서 반품 요청시 선택하신 **판매자에게 직접 송금**에 따라 아래 계좌로 송금 부탁드립니다.

🔹 송금 계좌
    • 은행명: 농협
    • 예금주: 양태영
    • 계좌번호: 301-5003-6206-81

🔹 송금 금액
    • {return_shipping_charge}원

송금 후 확인이 되면, 빠르게 반품 처리를 진행하도록 하겠습니다.
혹시 반품 관련하여 추가 문의사항이 있으시면, 02-338-9465로 연락 주시기 바랍니다.

항상 고객님의 만족을 위해 최선을 다하겠습니다.
감사합니다.
{store_name} 드림
"""
            
            message_list.append({
                "to": recipient_contact,
                "from": sender,
                "text": text,
                "type": "LMS"
            })

        payload = {"messages": message_list}

        # 인증에 필요한 date와 salt 생성
        # Google Apps Script 로직과 동일하게 UTC ISO8601 시간 사용
        date = datetime.datetime.utcnow().isoformat(timespec='seconds') + 'Z'  
        # isoformat(timespec='seconds') 사용 후 'Z'추가로 UTC 표기
        salt = uuid.uuid4().hex
        hmac_data = date + salt

        # HMAC-SHA256 서명 생성
        signature_bytes = hmac.new(
            api_secret.encode('utf-8'),
            hmac_data.encode('utf-8'),
            hashlib.sha256
        ).digest()

        # 바이트 배열을 소문자 hex 문자열로 변환
        signature = signature_bytes.hex()

        # Authorization 헤더 설정 (Google Apps Script 코드와 유사한 형식)
        authorization_header = f"HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}"

        headers = {
            "Content-Type": "application/json",
            "Authorization": authorization_header
        }

        response = requests.post(url, headers=headers, data=json.dumps(payload))

        if response.status_code == 200:
            return JsonResponse({"success": True, "message": "문자 발송 성공"})
        else:
            return JsonResponse({"success": False, "message": f"문자 발송 실패: {response.text}"})
    else:
        return JsonResponse({"success": False, "message": "Invalid request method"}, status=405)


@login_required
def process_return(request, item_id):
    print("process_return 함수 호출됨")  # 디버깅용 로그
    item = get_object_or_404(ReturnItem, id=item_id)
    print("플랫폼:", item.platform, "주문번호:", item.order_number)  # 디버깅용 로그

    # 플랫폼이 네이버인지 검사
    if item.platform.lower() == 'naver':
        # NAVER_ACCOUNTS에서 store_name 매칭 계정 찾기
        store_name = item.store_name
        target_account = next((acc for acc in NAVER_ACCOUNTS if store_name in acc['names']), None)
        if not target_account:
            print("해당 이름의 NAVER 계정을 찾지 못했습니다.")
            return False, "NAVER 계정을 찾을 수 없음"

        account_info = target_account

        # 네이버 반품 승인 API 호출 여부 결정
        # claim_type가 RETURN, N/A, (또는 '반품') 중 하나이고,
        # product_order_status가 DELIVERED, DELIVERING, PURCHASE_DECIDED (또는 '배송 중', '배송 완료', '구매 확정') 중 하나라면 API 호출
        condition_call_api = (
            item.claim_type in ['RETURN', 'N/A', '반품'] and 
            item.product_order_status in ['DELIVERED', 'DELIVERING', 'PURCHASE_DECIDED', '배송 중', '배송 완료', '구매 확정']
        )

        if condition_call_api:
            print("네이버 반품 승인 시작")  # 디버깅용 로그
            success, message = approve_naver_return(account_info, item.order_number)
            print("반품 승인 결과:", success, message)  # 디버깅용 로그

            if not success:
                print("네이버 반품 승인 실패:", message)
                return False, message
        else:
            # API 호출 없이 바로 반품완료 처리
            print("API 호출 없이 바로 반품완료 처리")
            message = "API 호출 없이 반품완료 처리"

        # 여기까지 오면 (API 성공이든, API 안 불렀든) '반품완료' 처리
        # ---- 핵심 변경: 주문번호 앞 12자리 공통인 아이템도 전부 '반품완료' ----
        order_prefix_12 = item.order_number[:12]
        print(f"DEBUG: order_prefix_12 = {order_prefix_12}")

        # 해당 prefix로 시작하는 아이템 전부 '반품완료'
        related_items = ReturnItem.objects.filter(
            order_number__startswith=order_prefix_12
        )
        print("연관 아이템들(12자리 기준):", related_items)

        # 이제 모든 related_items을 반품완료 처리
        for ri in related_items:
            ri.processing_status = '반품완료'
            ri.save()

        return True, "반품완료 처리 성공"

    elif item.platform.lower() == 'coupang':
        print("쿠팡 반품 승인 로직 시작")  # 디버깅용 로그
        # 여기는 즉시 '반품완료' 처리
        item.processing_status = '반품완료'
        item.save()
        return True, "쿠팡 반품완료 처리 성공"

    else:
        print(f"지원되지 않는 플랫폼({item.platform})")
        return False, "지원되지 않는 플랫폼"


@login_required
def process_return_bulk(request):
    """
    여러 아이템을 한꺼번에 '반품승인' 처리하는 뷰.
    내부적으로 process_return()을 호출.
    """
    if request.method == 'POST':
        item_ids = request.POST.getlist('item_ids')
        item_ids = [int(x) for x in item_ids if x.strip().isdigit()]

        success_list = []
        error_list = []

        for i_id in item_ids:
            success, msg = process_return(request, i_id)
            if success:
                success_list.append((i_id, msg))
            else:
                error_list.append((i_id, msg))

        if error_list:
            # 하나라도 오류가 있다면 실패로 처리
            return JsonResponse({
                'success': False,
                'errors': [{'id': eid, 'message': emsg} for eid, emsg in error_list]
            })
        else:
            return JsonResponse({
                'success': True,
                'message': '모든 반품승인 처리가 성공적으로 완료되었습니다.'
            })

    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def returned_items(request):
    # 반품 완료된 상품 목록 표시
    items = ReturnItem.objects.filter(processing_status='반품완료')
    return render(request, 'return_process/returned_items.html', {'items': items})

@login_required
def update_stock(request, item_id):
    item = get_object_or_404(ReturnItem, id=item_id)
    # 셀러툴 API 호출 로직
    url = 'https://api.sellertool.com/update_stock'
    data = {
        'product_id': item.product_id,
        'quantity': 1,  # 재고 수량 조정 로직에 따라 변경
    }
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()  # HTTP 오류 발생 시 예외 발생
    except requests.exceptions.RequestException as e:
        messages.error(request, f"재고 업데이트 실패: {e}")
        return redirect('returned_items')  # 또는 적절한 페이지로 리다이렉트

    # API 호출 성공 시 processing_status 업데이트
    item.processing_status = '재고반영'
    item.save()
    messages.success(request, f"재고가 성공적으로 반영되었습니다: {item.order_number}")
    return redirect('stock_updated_items')

@login_required
def stock_updated_items(request):
    items = ReturnItem.objects.filter(processing_status='재고반영')
    return render(request, 'return_process/stock_updated_items.html', {'items': items})

@login_required
def completed_items(request):
    items = ReturnItem.objects.filter(status='completed')
    return render(request, 'return_process/completed_items.html', {'items': items})

@login_required
def upload_returns(request):
    if request.method == 'POST':
        excel_file = request.FILES['excel_file']
        df = pd.read_excel(excel_file)
        for _, row in df.iterrows():
            ReturnItem.objects.update_or_create(
                order_id=row['주문번호'],
                defaults={
                    'customer_name': row['고객명'],
                    'product_name': row['상품명'],
                    'tracking_number': row['운송장번호'],
                    'status': 'pending',
                }
            )
        return redirect('return_list')
    return render(request, 'return_process/upload_returns.html')

def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # 회원가입 후 자동 로그인
            return redirect('반품목록')  # 회원가입 후 이동할 페이지
    else:
        form = CustomUserCreationForm()
    return render(request, 'return_process/signup.html', {'form': form})

def home(request):
    if request.user.is_authenticated:
        return redirect('반품목록')  # 로그인된 사용자는 반품목록으로 이동
    else:
        return redirect('login')  # 로그인되지 않은 사용자는 로그인 페이지로 이동
