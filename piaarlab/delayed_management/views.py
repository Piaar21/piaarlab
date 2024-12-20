import openpyxl
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .forms import DelayedOrderUploadForm, OptionStoreMappingUploadForm  
from .models import DelayedOrder, ProductOptionMapping ,OptionStoreMapping
from django.core.paginator import Paginator


def upload_delayed_orders(request):
    print("=== DEBUG: upload_delayed_orders 뷰 진입 ===")

    # 현재 세션에서 임시 데이터 가져오기
    temp_orders = request.session.get('delayed_orders_temp', [])

    if request.method == 'POST':
        print("=== DEBUG: POST 요청 감지 ===")
        print(f"=== DEBUG: POST keys={list(request.POST.keys())} ===")

        if 'upload_excel' in request.POST:
            print("=== DEBUG: 엑셀 업로드 로직 진입 ===")
            form = DelayedOrderUploadForm(request.POST, request.FILES)
            if form.is_valid():
                print("=== DEBUG: 폼 유효성 검사 통과 ===")
                file = request.FILES['file']
                print(f"=== DEBUG: 업로드된 파일 이름: {file.name} ===")
                wb = openpyxl.load_workbook(file, data_only=True)
                ws = wb.active
                print(f"=== DEBUG: 시트명: {ws.title}, 행수: {ws.max_row}, 열수: {ws.max_column} ===")

                new_temp_orders = []
                for idx, row in enumerate(ws.iter_rows(values_only=True)):
                    print(f"=== DEBUG: idx={idx}, row={row} ===")
                    if idx == 0:
                        print("=== DEBUG: 헤더 행 스킵 ===")
                        continue
                    if not row or len(row) < 9:
                        print("=== DEBUG: 유효하지 않은 행(컬럼 부족), 스킵 ===")
                        continue

                    option_code = (row[0] or "").strip()
                    customer_name = (row[1] or "").strip()
                    customer_contact = (row[2] or "").strip()
                    order_product_name = (row[3] or "").strip()
                    order_option_name = (row[4] or "").strip()
                    seller_product_name = (row[5] or "").strip()
                    seller_option_name = (row[6] or "").strip()
                    order_number_1 = (row[7] or "").strip()
                    order_number_2 = (row[8] or "").strip()

                    if not option_code:
                        print("=== DEBUG: 옵션코드 없음, 스킵 ===")
                        continue

                    # 스토어명 매핑
                    try:
                        store_map = OptionStoreMapping.objects.get(option_code=option_code)
                        store_name = store_map.store_name
                        print(f"=== DEBUG: 스토어명 매핑 성공: {option_code} -> {store_name} ===")
                    except OptionStoreMapping.DoesNotExist:
                        store_name = ""
                        print(f"=== DEBUG: 스토어명 매핑 실패: {option_code}에 해당하는 매핑 없음 ===")

                    order_data = {
                        'option_code': option_code,
                        'customer_name': customer_name,
                        'customer_contact': customer_contact,
                        'order_product_name': order_product_name,
                        'order_option_name': order_option_name,
                        'seller_product_name': seller_product_name,
                        'seller_option_name': seller_option_name,
                        'order_number_1': order_number_1,
                        'order_number_2': order_number_2,
                        'store_name': store_name
                    }
                    new_temp_orders.append(order_data)

                request.session['delayed_orders_temp'] = new_temp_orders
                print(f"=== DEBUG: {len(new_temp_orders)}건 임시 저장 완료 ===")
                messages.success(request, f"{len(new_temp_orders)}건이 임시로 업로드되었습니다.")
                return redirect('upload_delayed_orders')
            else:
                print("=== DEBUG: 폼 유효성 검사 실패 ===")
                messages.error(request, "파일 업로드에 실패했습니다. 폼이 유효하지 않습니다.")
                return redirect('upload_delayed_orders')

        elif 'finalize' in request.POST:
            print("=== DEBUG: 리스트 업로드(최종 저장) 로직 진입 ===")
            temp_orders = request.session.get('delayed_orders_temp', [])
            if not temp_orders:
                messages.error(request, "저장할 데이터가 없습니다.")
                print("=== DEBUG: 저장할 데이터 없음 ===")
                return redirect('upload_delayed_orders')

            row_count = 0
            for od in temp_orders:
                DelayedOrder.objects.create(**od)
                row_count += 1

            request.session['delayed_orders_temp'] = []
            print(f"=== DEBUG: {row_count}건 DB 저장 완료 ===")
            messages.success(request, f"{row_count}건의 지연 주문 정보가 DB에 저장되었습니다.")
            return redirect('post_list')

        elif 'delete_item' in request.POST:
            print("=== DEBUG: 임시 데이터 삭제 로직 진입 ===")
            index_to_delete = request.POST.get('delete_index')
            if index_to_delete is not None:
                temp_orders = request.session.get('delayed_orders_temp', [])
                print(f"=== DEBUG: 삭제 요청 인덱스: {index_to_delete}, 현재 임시 데이터 건수: {len(temp_orders)} ===")
                try:
                    index = int(index_to_delete)
                    if 0 <= index < len(temp_orders):
                        deleted_item = temp_orders[index]
                        del temp_orders[index]
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

        else:
            print("=== DEBUG: 알 수 없는 POST 요청 ===")
            messages.error(request, "잘못된 요청입니다.")
            return redirect('upload_delayed_orders')

    else:
        print("=== DEBUG: GET 요청으로 폼 페이지 로드 ===")

    # GET 요청 시 테이블에 세션 데이터 표시
    temp_orders = request.session.get('delayed_orders_temp', [])
    print(f"=== DEBUG: 현재 세션 임시 데이터 {len(temp_orders)}건 ===")
    return render(request, 'delayed_management/upload_delayed_orders.html', {
        'form': DelayedOrderUploadForm(),
        'temp_orders': temp_orders
    })


def post_list_view(request):
    return render(request, 'delayed_management/post_list.html')

def upload_file_view(request):
    print("=== DEBUG: upload_file_view 진입 ===")
    if request.method == 'POST':
        print("=== DEBUG: upload_file_view POST 요청 ===")
    return redirect('upload_delayed_orders')



from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from .models import OptionStoreMapping
from .forms import OptionStoreMappingUploadForm
from django.contrib import messages
import openpyxl

def upload_store_mapping(request):
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

    mappings_qs = OptionStoreMapping.objects.all().order_by('option_code')
    paginator = Paginator(mappings_qs, 30)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 페이지네이션 범위 계산 로직
    visible_pages = 5
    current = page_obj.number
    total = page_obj.paginator.num_pages

    # 기본적으로 현재 페이지를 중심으로 최대 5개 페이지 번호 표시
    half = visible_pages // 2
    start_page = current - half
    if start_page < 1:
        start_page = 1
    end_page = start_page + visible_pages - 1
    if end_page > total:
        end_page = total
        start_page = max(end_page - visible_pages + 1, 1)

    page_range_custom = range(start_page, end_page + 1)

    return render(request, 'delayed_management/upload_store_mapping.html', {
        'form': form,
        'mappings': page_obj,
        'page_obj': page_obj,
        'page_range_custom': page_range_custom  # 템플릿에 커스텀 페이지 범위 전달
    })


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