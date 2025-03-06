# rankings/views.py

import json
import logging
from django.db.models import Avg, Subquery, OuterRef,Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models.functions import TruncMinute
from django.db import IntegrityError
from django.views.decorators.csrf import csrf_protect
from django.contrib import messages  # 메시지 추가
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from django.forms import modelformset_factory
from django.urls import reverse  # reverse 함수 임포트 추가
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.csrf import csrf_exempt
from .forms import ProductForm, TrafficForm, UserProfileForm, AdForm, ExcelUploadForm, TaskForm
from .models import Product, Keyword, Ranking, Traffic, Task, UserProfile, Ad
from .resources import ProductResource
from tablib import Dataset
from celery import shared_task  # 추가
from .api_clients import get_naver_rank,naver_client_id, naver_client_secret  # Naver API 함수 임포트
import openpyxl  # 엑셀 파일 처리를 위한 openpyxl 임포트
from datetime import datetime, timedelta, date
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from django.utils.encoding import smart_str
from openpyxl import load_workbook  # 엑셀 파일 파싱을 위해



logger = logging.getLogger(__name__)


@login_required
def ranking_list(request):
    keywords = Keyword.objects.all()
    context = {
        'keywords': keywords
    }
    return render(request, 'rankings/ranking_list.html', context)

@login_required
def product_add(request):
    if request.method == 'POST':
        # 엑셀 파일이 업로드된 경우
        if 'upload_excel' in request.POST:
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "엑셀 파일을 선택해주세요.")
                return redirect('rankings:product_add')  # 네임스페이스 포함

            try:
                wb = openpyxl.load_workbook(excel_file)
                ws = wb.active

                # 헤더 매핑 정의
                header_mapping = {
                    '카테고리': 'category',
                    '상품명': 'name',
                    '순위 조회 키워드': 'search_keyword',  # 추가된 부분
                    '단일상품링크': 'single_product_link',
                    '단일상품 MID값': 'single_product_mid',
                    '원부 링크': 'original_link',
                    '원부 MID': 'original_mid',
                    '스토어명': 'store_name',
                    '담당자': 'manager',
                }

                # 첫 번째 행을 헤더로 가져오고, 필드 이름 매핑
                headers = [cell.value for cell in ws[1]]
                mapped_headers = [header_mapping.get(header, None) for header in headers]

                # 데이터 읽기
                data_list = []
                for row in ws.iter_rows(min_row=2, values_only=True):
                    row_data = {}
                    for idx, cell_value in enumerate(row):
                        field_name = mapped_headers[idx]
                        if field_name:  # 매핑된 필드만 저장
                            row_data[field_name] = cell_value if cell_value is not None else ''  # 수정된 부분
                    data_list.append(row_data)

                # 세션에 데이터 저장
                request.session['excel_data'] = data_list
                messages.success(request, "엑셀 데이터를 성공적으로 불러왔습니다. 확인 후 등록해주세요.")
                return redirect('rankings:product_add')

            except Exception as e:
                logger.error(f"엑셀 파일 처리 중 오류 발생: {e}")
                messages.error(request, "엑셀 파일을 읽는 중 오류가 발생했습니다. 파일 형식을 확인하세요.")
                return redirect('rankings:product_add')
            
        elif 'register_products' in request.POST:
            # 폼 데이터를 통해 등록하는 경우
            categories = request.POST.getlist('category[]')
            names = request.POST.getlist('name[]')
            search_keywords = request.POST.getlist('search_keyword[]')  # 추가된 부분
            single_product_links = request.POST.getlist('single_product_link[]')
            single_product_mids = request.POST.getlist('single_product_mid[]')
            original_links = request.POST.getlist('original_link[]')
            original_mids = request.POST.getlist('original_mid[]')
            store_names = request.POST.getlist('store_name[]')
            managers = request.POST.getlist('manager[]')  # 추가된 부분

            for i in range(len(names)):
                category = categories[i]
                name = names[i]
                search_keyword = search_keywords[i] if i < len(search_keywords) else ''  # 추가된 부분
                single_product_link = single_product_links[i]
                single_product_mid = single_product_mids[i]
                original_link = original_links[i]
                original_mid = original_mids[i]
                store_name = store_names[i]
                manager = managers[i] if i < len(managers) else ''
                
                # 필수 값 검증
                if not category or not name:
                    continue  # 필수 값이 없으면 해당 상품은 건너뜁니다

                Product.objects.create(
                    category=category,
                    name=name,
                    search_keyword=search_keyword,  # 추가된 부분
                    single_product_link=single_product_link,
                    single_product_mid=single_product_mid,
                    original_link=original_link,
                    original_mid=original_mid,
                    store_name=store_name,
                    manager=manager,
                )

            # 세션에서 엑셀 데이터 삭제
            if 'excel_data' in request.session:
                del request.session['excel_data']

            messages.success(request, "상품을 성공적으로 추가했습니다.")
            return redirect('rankings:product_list')
    else:
        form = ProductForm()

    # 세션에 엑셀 데이터가 있으면 컨텍스트에 전달
    excel_data = request.session.get('excel_data', [])
    return render(request, 'rankings/product_add.html', {'form': form, 'excel_data': excel_data})

@login_required
def download_product_sample_excel(request):
    # 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sample"

    # 헤더 설정
    headers = ['카테고리', '상품명', '순위 조회 키워드', '단일상품링크', '단일상품 MID값', '원부 링크', '원부 MID', '스토어명', '담당자']
    ws.append(headers)

    # 샘플 데이터 추가
    sample_data = [
        ['건강식품', '철분제', '철분제', 'http://example.com/product1', '123456', 'http://example.com/original1', '654321', '스토어1', '담당자1'],
        # 추가 샘플 데이터 필요 시 여기에 추가
    ]
    for row in sample_data:
        ws.append(row)

    # 열 너비 조정 및 정렬
    for column_cells in ws.columns:
        max_length = max(len(str(cell.value)) for cell in column_cells if cell.value)
        ws.column_dimensions[column_cells[0].column_letter].width = max_length + 2
        for cell in column_cells:
            cell.alignment = Alignment(horizontal='center', vertical='center')

    # 엑셀 파일로 응답
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=product_sample.xlsx'
    wb.save(response)
    return response


def product_list(request):
    products = Product.objects.all()
    context = {'products': products}
    return render(request, 'rankings/product_list.html', context)

@login_required
def task_register(request):
    # 이제 사용자 프로필에서 API 정보를 받지 않고, api_clients에 정의된 naver_client_id, naver_client_secret 사용
    if request.method == 'POST':
        if 'register' in request.POST:
            product_ids = request.POST.getlist('product_ids')
            if not product_ids:
                messages.warning(request, '상품을 선택해주세요.')
                return redirect('rankings:product_list')
            products = Product.objects.filter(id__in=product_ids)
            traffics = Traffic.objects.all()
            initial_data = build_initial_data_from_post(request, product_ids)  # 폼 재구성을 위한 initial_data 생성

            for product_id in product_ids:
                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    continue  # 존재하지 않는 상품은 건너뜁니다.

                # 폼에서 데이터 가져오기
                category = request.POST.get(f'category_{product_id}', '네이버')
                keyword_name = request.POST.get(f'keyword_{product_id}')
                url_type = request.POST.get(f'url_type_{product_id}')
                url = request.POST.get(f'url_{product_id}')
                memo = request.POST.get(f'memo_{product_id}')
                product_name = request.POST.get(f'product_name_{product_id}')
                traffic_id = request.POST.get(f'traffic_{product_id}')
                traffic = Traffic.objects.get(id=traffic_id) if traffic_id else None

                # 필수 필드 검증
                missing_fields = []
                if not category:
                    missing_fields.append('카테고리')
                if not keyword_name:
                    missing_fields.append('순위조회키워드')
                if not url_type:
                    missing_fields.append('URL 타입')
                if not url:
                    missing_fields.append('URL')
                if not product_name:
                    missing_fields.append('상품명')

                # ticket_count를 정수로 변환
                ticket_count_str = request.POST.get(f'ticket_count_{product_id}')
                if ticket_count_str:
                    try:
                        ticket_count = int(ticket_count_str)
                    except ValueError:
                        missing_fields.append('이용권 수 (숫자여야 합니다)')
                        ticket_count = None
                else:
                    missing_fields.append('이용권 수')
                    ticket_count = None

                # 날짜 필드를 datetime.date로 변환
                available_start_date_str = request.POST.get(f'available_start_date_{product_id}')
                available_end_date_str = request.POST.get(f'available_end_date_{product_id}')

                try:
                    available_start_date = datetime.strptime(available_start_date_str, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    missing_fields.append('이용가능 시작일자 (올바른 날짜 형식이어야 합니다)')
                    available_start_date = None

                try:
                    available_end_date = datetime.strptime(available_end_date_str, '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    missing_fields.append('이용가능 종료일자 (올바른 날짜 형식이어야 합니다)')
                    available_end_date = None

                if missing_fields:
                    error_message = f"상품 ID {product_id}: 다음 필드를 확인해주세요: {', '.join(missing_fields)}"
                    initial_data = build_initial_data_from_post(request, product_ids)
                    return render(request, 'rankings/task_register.html', {
                        'error': error_message,
                        'products': products,
                        'traffics': traffics,
                        'initial_data': initial_data,
                    })

                # Keyword 인스턴스 가져오기 또는 생성
                keyword_obj, created = Keyword.objects.get_or_create(name=keyword_name)

                # Naver API를 사용하여 시작 순위 가져오기
                # user 대신 api_clients에 정의된 API 정보를 활용합니다.
                try:
                    start_rank = get_naver_rank(keyword_name, url)
                    print(f"Start rank for keyword '{keyword_name}': {start_rank}")
                except Exception as e:
                    print(f"Error in get_naver_rank: {e}")
                    error_message = f"Naver API 호출 중 오류 발생: {str(e)}"
                    initial_data = build_initial_data_from_post(request, product_ids)
                    return render(request, 'rankings/task_register.html', {
                        'error': error_message,
                        'products': products,
                        'traffics': traffics,
                        'initial_data': initial_data,
                    })

                if start_rank == -1 or start_rank > 1000:
                    start_rank = None  # 검색 결과가 없거나 1000위 초과면 None으로 설정

                # 현재 순위와 어제 순위는 등록 시 동일하게 설정
                yesterday_rank = start_rank
                current_rank = start_rank
                difference_rank = 0  # 처음 등록 시 차이는 0

                # Task 생성
                try:
                    task = Task.objects.create(
                        product=product,
                        category=category,
                        keyword=keyword_obj,
                        url=url,
                        start_rank=start_rank,
                        yesterday_rank=yesterday_rank,
                        current_rank=current_rank,
                        difference_rank=difference_rank,
                        memo=memo,
                        product_name=product_name,
                        ticket_count=ticket_count,
                        available_start_date=available_start_date,
                        available_end_date=available_end_date,
                        traffic=traffic,
                    )
                    # Ranking 객체 생성
                    Ranking.objects.create(
                        task=task,
                        product=task.product,
                        keyword=keyword_obj,
                        rank=start_rank if start_rank is not None else 1000,
                        date_time=timezone.now(),
                    )
                except Exception as e:
                    error_message = f"작업 생성 중 오류 발생: {str(e)}"
                    initial_data = build_initial_data_from_post(request, product_ids)
                    return render(request, 'rankings/task_register.html', {
                        'error': error_message,
                        'products': products,
                        'traffics': traffics,
                        'initial_data': initial_data,
                    })

            messages.success(request, '작업이 성공적으로 등록되었습니다.')
            return redirect('rankings:dashboard')
        else:
            messages.error(request, '잘못된 요청입니다.')
            return redirect('rankings:product_list')
    else:
        # GET 요청 처리
        selected_product_ids = request.GET.getlist('selected_products')
        if not selected_product_ids:
            messages.warning(request, '상품을 선택해주세요.')
            return redirect('rankings:product_list')
        products = Product.objects.filter(id__in=selected_product_ids)
        initial_data = {}
        for product in products:
            initial_data[product.id] = {
                'keyword': product.search_keyword or '',
                'url_type': '',
                'url': '',
                'memo': '',
                'product_name': product.name,
                'traffic_id': '',
                'ticket_count': '',
                'available_start_date': '',
                'available_end_date': '',
            }
        traffics = Traffic.objects.all()
        context = {
            'products': products,
            'traffics': traffics,
            'initial_data': initial_data,
        }
        return render(request, 'rankings/task_register.html', context)
    
@login_required
def task_upload_excel_data(request):
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            return JsonResponse({'success': False, 'error': '엑셀 파일이 전송되지 않았습니다.'})

        try:
            # 1) 엑셀 파일 파싱
            wb = load_workbook(filename=excel_file, data_only=True)
            ws = wb.active  # 활성화된 sheet 하나를 사용 (여러 시트라면 추가 로직 필요)

            # 2) 엑셀 내 데이터 추출 예시
            #    예: A열: 상품 ID / B열: 카테고리 / C열: 키워드 / D열: URL / ...
            #    원하는 형식으로 엑셀 구조를 정한 다음, 파싱 로직 작성
            tasks_to_create = []
            for row in ws.iter_rows(min_row=2, values_only=True):  # 헤더 제외, 2행부터
                product_id = row[0]
                category = row[1]
                keyword_name = row[2]
                url = row[3]
                memo = row[4]
                product_name = row[5]
                ticket_count = row[6]
                available_start_date = row[7]  # datetime
                available_end_date = row[8]

                # product_id에 맞는 Product 객체 가져오기
                try:
                    product = Product.objects.get(id=product_id)
                except Product.DoesNotExist:
                    # 존재하지 않는 product면 무시하거나, 로직 추가
                    continue

                # NAVER 랭킹 조회 로직 재사용 (혹은 별도 함수화)
                start_rank = get_naver_rank(keyword_name, url)
                if start_rank == -1 or start_rank > 1000:
                    start_rank = None

                # Keyword 생성 or get
                keyword_obj, created = Keyword.objects.get_or_create(name=keyword_name)

                # 작업 생성 준비
                tasks_to_create.append({
                    'product': product,
                    'category': category,
                    'keyword': keyword_obj,
                    'url': url,
                    'start_rank': start_rank,
                    'yesterday_rank': start_rank,
                    'current_rank': start_rank,
                    'difference_rank': 0,
                    'memo': memo,
                    'product_name': product_name,
                    'ticket_count': ticket_count if ticket_count else 0,
                    'available_start_date': available_start_date,
                    'available_end_date': available_end_date,
                })

            # 3) 실제 DB에 Task 생성 & Ranking 생성
            for task_data in tasks_to_create:
                task = Task.objects.create(**task_data)
                Ranking.objects.create(
                    task=task,
                    product=task.product,
                    keyword=task.keyword,
                    rank=task.start_rank if task.start_rank is not None else 1000,
                    date_time=timezone.now()
                )

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    else:
        return JsonResponse({'success': False, 'error': 'POST 요청이 아닙니다.'})


@login_required
def download_bulk_traffic_sample_excel(request):
    # 오늘 날짜 기준 내일과 10일 뒤 날짜 계산
    today = timezone.localdate()
    start_date = today + timedelta(days=1)
    end_date = today + timedelta(days=10)

    # GET 파라미터에서 선택된 트래픽 ID 가져오기
    traffic_id = request.GET.get('traffic_id')
    traffic = None
    if traffic_id:
        try:
            traffic = Traffic.objects.get(id=traffic_id)
        except Traffic.DoesNotExist:
            traffic = None

    # 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active

    # 헤더 설정
    headers = [
        '상품ID', 
        '카테고리', 
        '순위조회키워드', 
        'URL', 
        '메모', 
        '상품명', 
        '이용권수', 
        '이용가능 시작일자', 
        '이용가능 종료일자'
    ]
    ws.append(headers)

    # DB에 등록된 모든 상품 조회
    products = Product.objects.all()
    for product in products:
        # 트래픽 선택에 따라 URL 결정
        if traffic:
            if traffic.type == '단일':
                url = product.single_product_link or ''
            elif traffic.type == '원부':
                url = product.original_link or ''
            else:
                url = ''
        else:
            # 트래픽 미선택 시 기본적으로 단일 링크 사용
            url = product.single_product_link or ''

        row = [
            product.id,                          # 상품ID
            "네이버",                            # 카테고리 (항상 네이버)
            product.search_keyword or '',        # 순위조회키워드
            url,                                 # URL (트래픽에 따른 단일/원부 선택)
            '',                                  # 메모 (빈 값)
            product.name or '',                  # 상품명
            1,                                   # 이용권수 (항상 1)
            start_date.strftime('%Y-%m-%d'),      # 이용가능 시작일자 (내일)
            end_date.strftime('%Y-%m-%d'),        # 이용가능 종료일자 (10일 뒤)
        ]
        ws.append(row)

    # 열 너비 자동 조정
    for column_cells in ws.columns:
        max_length = 0
        for cell in column_cells:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        column_letter = column_cells[0].column_letter
        ws.column_dimensions[column_letter].width = max_length + 2

    # 엑셀 파일 응답 생성
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename=bulk_task_sample.xlsx'
    wb.save(response)
    return response



def build_initial_data_from_post(request, product_ids):
    initial_data = {}
    for product_id in product_ids:
        initial_data[int(product_id)] = {
            'keyword': request.POST.get(f'keyword_{product_id}', ''),
            'url_type': request.POST.get(f'url_type_{product_id}', ''),
            'url': request.POST.get(f'url_{product_id}', ''),
            'memo': request.POST.get(f'memo_{product_id}', ''),
            'product_name': request.POST.get(f'product_name_{product_id}', ''),
            'traffic_id': request.POST.get(f'traffic_{product_id}', ''),
            'ticket_count': request.POST.get(f'ticket_count_{product_id}', ''),
            'available_start_date': request.POST.get(f'available_start_date_{product_id}', ''),
            'available_end_date': request.POST.get(f'available_end_date_{product_id}', ''),
        }
    return initial_data




def build_initial_data_from_post(request, product_ids):
    initial_data = {}
    for product_id in product_ids:
        initial_data[int(product_id)] = {
            'keyword': request.POST.get(f'keyword_{product_id}', ''),
            'url_type': request.POST.get(f'url_type_{product_id}', ''),
            'url': request.POST.get(f'url_{product_id}', ''),
            'memo': request.POST.get(f'memo_{product_id}', ''),
            'product_name': request.POST.get(f'product_name_{product_id}', ''),
            'traffic_id': request.POST.get(f'traffic_{product_id}', ''),
            'ticket_count': request.POST.get(f'ticket_count_{product_id}', ''),
            'available_start_date': request.POST.get(f'available_start_date_{product_id}', ''),
            'available_end_date': request.POST.get(f'available_end_date_{product_id}', ''),
        }
    return initial_data

def get_products_with_latest_task(request, selected_product_ids):
    return Product.objects.filter(id__in=selected_product_ids).annotate(
        latest_task_id=Subquery(
            Task.objects.filter(product=OuterRef('pk')).order_by('-created_at').values('id')[:1]
        ),
        yesterday_rank_annotated=Subquery(
            Task.objects.filter(id=OuterRef('latest_task_id')).values('yesterday_rank')
        ),
        current_rank_annotated=Subquery(
            Task.objects.filter(id=OuterRef('latest_task_id')).values('current_rank')
        ),
        start_rank_annotated=Subquery(
            Task.objects.filter(id=OuterRef('latest_task_id')).values('start_rank')
        ),
        last_checked_date_annotated=Subquery(
            Task.objects.filter(id=OuterRef('latest_task_id')).values('last_checked_date')
        )
    )

@login_required
def dashboard(request):
    today = timezone.now().date()
    tasks_list = Task.objects.filter(
        
        available_end_date__gte=today
    ).order_by('created_at').select_related('traffic', 'product')  # product를 select_related에 추가

    # 페이지네이션 설정
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 50)
    per_page_options = [50, 100, 150, 300]

    # per_page 값 검증
    try:
        per_page = int(per_page)
        if per_page not in per_page_options:
            per_page = 50
    except ValueError:
        per_page = 50

    paginator = Paginator(tasks_list, per_page)

    try:
        tasks = paginator.page(page)
    except PageNotAnInteger:
        tasks = paginator.page(1)
    except EmptyPage:
        tasks = paginator.page(paginator.num_pages)

    context = {
        'tasks': tasks,
        'per_page_options': per_page_options,
        'selected_per_page': per_page,
    }
    return render(request, 'rankings/dashboard.html', context)

@login_required
def completed_tasks_list(request):
    completed_tasks_list = Task.objects.filter(is_completed=True).order_by('-available_end_date')

    # 페이지네이션 설정
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    per_page_options = [10, 30, 50, 100]

    # per_page 값 검증
    try:
        per_page = int(per_page)
        if per_page not in per_page_options:
            per_page = 10
    except ValueError:
        per_page = 10

    paginator = Paginator(completed_tasks_list, per_page)

    try:
        tasks = paginator.page(page)
    except PageNotAnInteger:
        tasks = paginator.page(1)
    except EmptyPage:
        tasks = paginator.page(paginator.num_pages)

    context = {
        'tasks': tasks,
        'per_page_options': per_page_options,
        'selected_per_page': per_page,
    }

    return render(request, 'rankings/completed_tasks_list.html', context)

def process_task_registration(request, product_ids, products, traffics, initial_data):
    for product_id in product_ids:
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            continue  # 다음 상품으로 이동

        # 나머지 코드 진행
        category = request.POST.get(f'category_{product_id}', '네이버')
        keyword_name = request.POST.get(f'keyword_{product_id}')
        url_type = request.POST.get(f'url_type_{product_id}')
        url = request.POST.get(f'url_{product_id}')
        memo = request.POST.get(f'memo_{product_id}')
        product_name = request.POST.get(f'product_name_{product_id}')
        traffic_id = request.POST.get(f'traffic_{product_id}')
        traffic = Traffic.objects.get(id=traffic_id) if traffic_id else None

        # 필수 필드 검증
        missing_fields = []
        if not category:
            missing_fields.append('category')
        if not keyword_name:
            missing_fields.append('keyword')
        if not url_type:
            missing_fields.append('url_type')
        if not url:
            missing_fields.append('url')
        if not product_name:
            missing_fields.append('product_name')

        # ticket_count를 정수로 변환
        ticket_count_str = request.POST.get(f'ticket_count_{product_id}')
        if ticket_count_str:
            try:
                ticket_count = int(ticket_count_str)
            except ValueError:
                missing_fields.append('ticket_count (숫자여야 합니다)')
                ticket_count = None
        else:
            missing_fields.append('ticket_count')
            ticket_count = None

        # 날짜 필드를 datetime.date로 변환
        available_start_date_str = request.POST.get(f'available_start_date_{product_id}')
        available_end_date_str = request.POST.get(f'available_end_date_{product_id}')

        try:
            available_start_date = datetime.strptime(available_start_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            missing_fields.append('available_start_date (올바른 날짜 형식이어야 합니다)')
            available_start_date = None

        try:
            available_end_date = datetime.strptime(available_end_date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            missing_fields.append('available_end_date (올바른 날짜 형식이어야 합니다)')
            available_end_date = None

        if missing_fields:
            error_message = f"Product ID {product_id}: Missing or invalid fields: {', '.join(missing_fields)}"
            return render(request, 'rankings/task_register.html', {'error': error_message, 'products': products, 'traffics': traffics, 'initial_data': initial_data})

        # Keyword 인스턴스 가져오기 또는 생성
        keyword_obj, created = Keyword.objects.get_or_create(name=keyword_name)

        # Naver API를 사용하여 시작 순위 가져오기
        try:
            start_rank = get_naver_rank(keyword_name, url)
            print(f"Start rank for keyword '{keyword_name}': {start_rank}")
        except Exception as e:
            print(f"Error in get_naver_rank: {e}")
            error_message = f"Naver API 호출 중 오류 발생: {str(e)}"
            return render(request, 'rankings/task_register.html', {'error': error_message, 'products': products, 'traffics': traffics, 'initial_data': initial_data})

        if start_rank == -1 or start_rank > 1000:
            start_rank = None  # 검색 결과에 없거나 1000위 초과인 경우 None으로 설정

        # 현재 순위와 어제 순위는 작업 등록 시점에서는 동일하게 설정
        yesterday_rank = start_rank
        current_rank = start_rank
        difference_rank = 0  # 처음 등록 시 차이는 0

        # Task 생성
        try:
            task = Task.objects.create(
                product=product,
                category=category,
                keyword=keyword_obj,
                url=url,
                start_rank=start_rank,
                yesterday_rank=yesterday_rank,
                current_rank=current_rank,
                difference_rank=difference_rank,
                memo=memo,
                product_name=product_name,
                ticket_count=ticket_count,
                available_start_date=available_start_date,
                available_end_date=available_end_date,
                traffic=traffic,
            )
        except Exception as e:
            error_message = f"작업 생성 중 오류 발생: {str(e)}"
            return render(request, 'rankings/task_register.html', {'error': error_message, 'products': products, 'traffics': traffics, 'initial_data': initial_data})

    messages.success(request, '작업이 성공적으로 등록되었습니다.')
    return redirect('rankings:dashboard')  # 작업 등록 후 대시보드로 이동

@login_required
def task_reregister(request):

    if request.method == 'POST':
        if 'register' in request.POST:
            # 작업 등록 로직
            product_ids = request.POST.getlist('product_ids')
            if not product_ids:
                return redirect('rankings:product_list')
            products = Product.objects.filter(id__in=product_ids)
            traffics = Traffic.objects.all()
            initial_data = build_initial_data_from_post(request, product_ids)
            # process_task_registration 함수 호출
            return process_task_registration(request, product_ids, products, traffics, initial_data)
        else:
            # 선택된 작업으로 폼 초기화
            selected_task_ids = request.POST.getlist('selected_tasks')
            if not selected_task_ids:
                messages.warning(request, '작업을 선택해주세요.')
                return redirect('rankings:completed_tasks_list')
            tasks = Task.objects.filter(id__in=selected_task_ids)
            products = [task.product for task in tasks]
            traffics = Traffic.objects.all()
            context = {
                'products': products,
                'traffics': traffics,
            }
            return render(request, 'rankings/task_register.html', context)
    else:
        # GET 요청 처리
        selected_task_ids = request.GET.get('task_ids')
        if not selected_task_ids:
            messages.warning(request, '작업을 선택해주세요.')
            return redirect('rankings:completed_tasks_list')
        task_ids = selected_task_ids.split(',')
        tasks = Task.objects.filter(id__in=task_ids)
        products = [task.product for task in tasks]
        traffics = Traffic.objects.all()
        # initial_data 구성
        initial_data = {}
        for task in tasks:
            product_id = task.product.id  # 정수형 유지
            # URL 타입 결정
            if task.url == task.product.single_product_link:
                url_type = 'single'
            elif task.url == task.product.original_link:
                url_type = 'original'
            else:
                url_type = ''
            initial_data[product_id] = {  # 키를 정수형으로 사용
                'keyword': task.keyword.name,
                'url_type': url_type,
                'url': task.url,
                'memo': task.memo,
                'traffic_id': str(task.traffic.id) if task.traffic else '',
                'ticket_count': task.ticket_count,
                'available_start_date': task.available_start_date.strftime('%Y-%m-%d') if task.available_start_date else '',
                'available_end_date': task.available_end_date.strftime('%Y-%m-%d') if task.available_end_date else '',
            }
        context = {
            'products': products,
            'traffics': traffics,
            'initial_data': initial_data,
        }
        return render(request, 'rankings/task_register.html', context)

@login_required
def product_bulk_edit(request):
    ProductFormSet = modelformset_factory(
        Product,
        form=ProductForm,
        fields=[
            'id',
            'category',
            'name',
            'search_keyword',
            'single_product_link',
            'single_product_mid',
            'original_link',
            'original_mid',
            'store_name',
            'manager',
        ],
        extra=0
    )

    if request.method == 'POST':
        # 폼셋이 제출된 경우
        formset = ProductFormSet(request.POST)
        if formset.is_valid():
            instances = formset.save(commit=False)
            for instance in instances:
                instance.user = request.user
                instance.save()
            messages.success(request, "선택한 상품이 성공적으로 수정되었습니다.")
            return redirect('rankings:product_list')
        else:
            messages.error(request, "폼에 오류가 있습니다. 확인해주세요.")
    else:
        # GET 요청 처리: 선택된 상품 IDs를 가져옵니다.
        selected_ids = request.GET.getlist('selected_products')
        if not selected_ids:
            messages.error(request, "수정할 상품을 선택해주세요.")
            return redirect('rankings:product_list')
        products = Product.objects.filter(id__in=selected_ids)
        formset = ProductFormSet(queryset=products)

    return render(request, 'rankings/product_bulk_edit.html', {'formset': formset})



@login_required
def average_ranking(request):
    task_id = request.GET.get('task_id')
    if not task_id:
        return redirect('rankings:dashboard')

    task = get_object_or_404(Task, id=task_id)

    rankings = Ranking.objects.filter(
        product=task.product,
        keyword=task.keyword,
    ).annotate(
        time=TruncMinute('date_time')
    ).order_by('time')
    print(f"Rankings count: {rankings.count()}")

    dates = [ranking.time.strftime('%Y-%m-%d %H:%M') for ranking in rankings]
    ranks = [ranking.rank for ranking in rankings]

    context = {
        'task': task,
        'dates': json.dumps(dates),
        'ranks': json.dumps(ranks),
    }

    return render(request, 'rankings/average_ranking.html', context)

@login_required
def issues(request):
    # GET 파라미터에서 현재 페이지 번호와 페이지 당 항목 수를 가져옵니다.
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)

    # 페이지 당 항목 수 옵션 설정
    per_page_options = [10, 30, 50, 100]

    # 유효한 페이지 당 항목 수인지 확인하고, 아니면 기본값 10으로 설정
    try:
        per_page = int(per_page)
        if per_page not in per_page_options:
            per_page = 10
    except ValueError:
        per_page = 10

    # current_rank가 None이거나 1000위 초과인 Task를 필터링합니다.
    problematic_tasks = Task.objects.filter(
        Q(current_rank__isnull=True) | Q(current_rank__gt=1000)
    )
    # Paginator를 사용하여 쿼리셋을 페이지네이션합니다.
    paginator = Paginator(problematic_tasks, per_page)

    try:
        tasks = paginator.page(page)
    except PageNotAnInteger:
        # 페이지 번호가 정수가 아니면 첫 번째 페이지를 보여줍니다.
        tasks = paginator.page(1)
    except EmptyPage:
        # 페이지 번호가 범위를 벗어나면 마지막 페이지를 보여줍니다.
        tasks = paginator.page(paginator.num_pages)

    context = {
        'tasks': tasks,
        'per_page_options': per_page_options,
        'selected_per_page': per_page,
    }
    return render(request, 'rankings/issues.html', context)

@login_required
def traffic_bulk_edit(request):
    TrafficFormSet = modelformset_factory(Traffic, form=TrafficForm, extra=0)
    if request.method == 'POST':
        if 'edit_traffics' in request.POST:
            # 선택된 트래픽을 가져와 폼셋 생성 (초기 로딩 시)
            selected_ids = request.POST.getlist('selected_traffics')
            if not selected_ids:
                messages.error(request, "수정할 트래픽을 선택해주세요.")
                return redirect('rankings:traffic_list')
            traffics = Traffic.objects.filter(id__in=selected_ids)
            formset = TrafficFormSet(queryset=traffics)
        else:
            # 폼셋 제출 시 데이터 처리
            formset = TrafficFormSet(request.POST)
            if formset.is_valid():
                instances = formset.save(commit=False)
                for instance in instances:
                    instance.user = request.user
                    instance.save()
                messages.success(request, "선택한 트래픽이 성공적으로 수정되었습니다.")
                return redirect('rankings:traffic_list')
            else:
                messages.error(request, "폼에 오류가 있습니다. 확인해주세요.")
    else:
        messages.error(request, "잘못된 접근입니다.")
        return redirect('rankings:traffic_list')
    return render(request, 'rankings/traffic_bulk_edit.html', {'formset': formset})



@login_required
def task_update(request):
    if request.method == 'POST':
        next_url = request.POST.get('next', reverse('rankings:dashboard'))
        logger.debug(f"Received POST request with next_url: {next_url}")

        task_ids = [key.split('_')[1] for key in request.POST.keys() if key.startswith('category_')]
        logger.debug(f"Task IDs to update: {task_ids}")

        for task_id in task_ids:
            try:
                task = get_object_or_404(Task, id=task_id)
                new_product_id = request.POST.get(f'product_id_{task_id}')
                new_keyword_name = request.POST.get(f'keyword_{task_id}')
                new_url = request.POST.get(f'url_{task_id}')
                new_category = request.POST.get(f'category_{task_id}')
                new_memo = request.POST.get(f'memo_{task_id}')

                # 새로운 날짜 값 가져오기
                new_available_start_date = request.POST.get(f'available_start_date_{task_id}')
                new_available_end_date = request.POST.get(f'available_end_date_{task_id}')

                # 날짜 형식 변환
                date_format = "%Y-%m-%d"
                if new_available_start_date:
                    new_available_start_date = datetime.strptime(new_available_start_date, date_format).date()
                if new_available_end_date:
                    new_available_end_date = datetime.strptime(new_available_end_date, date_format).date()

                # 필수 필드 검증
                if not new_keyword_name:
                    messages.error(request, f"작업 ID {task_id}의 키워드가 입력되지 않았습니다.")
                    continue
                if not new_url:
                    messages.error(request, f"작업 ID {task_id}의 URL이 입력되지 않았습니다.")
                    continue

                # 상품이 변경되었는지 확인
                if new_product_id and int(new_product_id) != task.product.id:
                    # 기존 작업 종료 처리
                    task.available_end_date = timezone.localdate()
                    task.save()

                    # 새로운 작업 생성
                    new_product = get_object_or_404(Product, id=new_product_id)
                    keyword_obj, _ = Keyword.objects.get_or_create(name=new_keyword_name)

                    # **available_start_date를 내일 날짜로 설정**
                    new_task = Task.objects.create(
                        product=new_product,
                        category=new_category,
                        keyword=keyword_obj,
                        url=new_url,
                        memo=new_memo,
                        product_name=new_product.name,
                        ticket_count=task.ticket_count,
                        available_start_date=timezone.localdate() + timedelta(days=1),
                        available_end_date=new_available_end_date or task.available_end_date,
                        traffic=task.traffic,
                    )
                    # 순위 조회 및 저장 (필요 시)
                else:
                    # 기존 작업 수정
                    old_keyword_name = task.keyword.name
                    old_url = task.url
                    task.category = new_category
                    keyword_obj, _ = Keyword.objects.get_or_create(name=new_keyword_name)
                    task.keyword = keyword_obj
                    task.url = new_url
                    task.memo = new_memo

                    # **available_start_date를 폼에서 제출된 값으로 업데이트**
                    if new_available_start_date:
                        task.available_start_date = new_available_start_date

                    # **available_end_date도 동일하게 처리**
                    if new_available_end_date:
                        task.available_end_date = new_available_end_date

                    task.save()
                    # 키워드 또는 URL이 변경되었는지 확인하여 순위 조회 수행 (필요 시)
            except Exception as e:
                logger.error(f"Error updating task {task_id}: {e}")
                messages.error(request, f"작업 ID {task_id} 업데이트 중 오류가 발생했습니다.")

        logger.debug(f"Redirecting to: {next_url}")
        return redirect(next_url)
    else:
        try:
            task_ids = request.GET.get('task_ids')
            next_url = request.GET.get('next', reverse('rankings:dashboard'))
            products = Product.objects.all()  # 모든 상품 가져오기

            if task_ids:
                task_id_list = task_ids.split(',')
                tasks = Task.objects.filter(id__in=task_id_list)
                if not tasks.exists():
                    messages.error(request, '선택한 작업을 찾을 수 없습니다.')
                    return redirect('rankings:task_list')
            else:
                messages.error(request, '수정할 작업을 선택해주세요.')
                return redirect('rankings:task_list')

            context = {
                'tasks': tasks,
                'products': products,  # 컨텍스트에 products 추가
                'next_url': next_url,  # 컨텍스트에 next_url 추가
            }
            return render(request, 'rankings/task_edit.html', context)
        except Exception as e:
            logger.error(f"Error in task_update GET: {e}")
            messages.error(request, '요청을 처리하는 중 오류가 발생했습니다.')
            return redirect('rankings:dashboard')


@csrf_protect
def product_delete(request):
    if request.method == 'POST':
        selected_product_ids = request.POST.getlist('selected_products')
        if selected_product_ids:
            Product.objects.filter(id__in=selected_product_ids).delete()
        return redirect('rankings:product_list')


@login_required
def traffic_register(request):
    if request.method == 'POST':
        if 'upload_excel' in request.POST:
            # 엑셀 업로드 처리
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "엑셀 파일을 선택해주세요.")
                return redirect('rankings:traffic_register')
            # 엑셀 파일 읽기
            try:
                wb = openpyxl.load_workbook(excel_file)
                sheet = wb.active
                traffics_data = []
                
                for row in sheet.iter_rows(min_row=2, values_only=True):  # 헤더 제외
                    # 엑셀 파일의 열 순서에 따라 데이터 매핑
                    name = row[0]
                    price = row[1]
                    method = row[2]
                    days = row[3]
                    inflow_count = row[4]
                    link = row[5].strip() if row[5] else ''  # 링크가 없으면 빈 문자열 처리
                    vendor = row[6] if len(row) > 6 else ''  # 업체명 (추가된 부분)
                    type_value = row[7] if len(row) > 7 else ''  # 노출방식 (추가된 부분)
                    # 필수 값 검증
                    if not (name and price and method and days and inflow_count):
                        continue  # 필수 값이 없으면 건너뜁니다

                    # 데이터 타입 변환 및 유효성 검사
                    try:
                        price = int(price)
                        days = int(days)
                        inflow_count = int(inflow_count)
                    except ValueError:
                        continue  # 값이 유효하지 않으면 건너뜁니다

                        # 링크에 스킴 추가
                    if link and not link.startswith(('http://', 'https://')):
                        link = 'http://' + link

                    # 트래픽 데이터를 리스트에 추가
                    traffics_data.append({
                        'name': name,
                        'price': price,
                        'method': method,
                        'days': days,
                        'inflow_count': inflow_count,
                        'link': link,
                        'vendor': vendor,  
                        'type': type_value,  # 추가된 부분

                    })

                # traffics_data를 컨텍스트에 전달하여 폼에 표시
                return render(request, 'rankings/traffic_register.html', {'traffics_data': traffics_data})

            except Exception as e:
                print(f"Error processing the file: {e}")
                messages.error(request, f"엑셀 파일 처리 중 오류 발생: {e}")
                return redirect('rankings:traffic_register')

        elif 'register_traffic' in request.POST:
            # 폼 데이터 처리
            names = request.POST.getlist('name')
            prices = request.POST.getlist('price')
            methods = request.POST.getlist('method')
            days_list = request.POST.getlist('days')
            inflow_counts = request.POST.getlist('inflow_count')
            links = request.POST.getlist('link')
            vendors = request.POST.getlist('vendor')  
            types = request.POST.getlist('type')  # 추가된 부분: 노출방식
            for i in range(len(names)):
                name = names[i]
                price = prices[i]
                method = methods[i]
                days = days_list[i]
                inflow_count = inflow_counts[i]
                link = links[i].strip() if links[i] else ''  # 링크가 없으면 빈 문자열로 저장
                vendor = vendors[i].strip() if vendors[i] else ''  # 링크가 없으면 빈 문자열로 저장
                type_value = types[i].strip() if types[i] else ''  # 추가된 부분: 노출방식

                # 필수 값 검증
                if not (name and price and method and days and inflow_count):
                    continue  # 필수 값이 없으면 건너뜁니다

                # 데이터 타입 변환
                try:
                    price = int(price)  # 정수형으로 변환하여 소숫점 제거
                    days = int(days)
                    inflow_count = int(inflow_count)
                except ValueError:
                    continue  # 값이 유효하지 않으면 건너뜁니다

                # 링크에 스킴 추가
                if link and not link.startswith(('http://', 'https://')):
                    link = 'http://' + link

                # 트래픽 생성
                Traffic.objects.create(
                    name=name,
                    price=price,
                    method=method,
                    days=days,
                    inflow_count=inflow_count,
                    link=link or '',
                    vendor=vendor,  # 추가된 부분
                    type=type_value,  # 추가된 부분

                )
            messages.success(request, "트래픽을 성공적으로 등록했습니다.")
            return redirect('rankings:traffic_list')

    else:
        return render(request, 'rankings/traffic_register.html')



@login_required
def traffic_delete(request):
    if request.method == 'POST':
        selected_traffic_ids = request.POST.getlist('selected_traffics')
        if selected_traffic_ids:
            Traffic.objects.filter(id__in=selected_traffic_ids).delete()
            messages.success(request, "선택한 트래픽을 삭제했습니다.")
        else:
            messages.warning(request, "삭제할 트래픽을 선택해주세요.")
    return redirect('rankings:traffic_list')

@login_required
def download_traffic_sample_excel(request):
    # 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active

    # 헤더 설정
    headers = ['트래픽명', '금액', '방식', '일자', '유입수', '링크', '업체명']
    ws.append(headers)

    # 데이터 추가
    data = ['피날레', 30000, '리워드', 10, 10000, 'www.example.com','Sample Vendor']
    ws.append(data)

    # 열 너비 조정 및 정렬
    for column_cells in ws.columns:
        length = max(len(str(cell.value)) for cell in column_cells)
        column_letter = column_cells[0].column_letter
        ws.column_dimensions[column_letter].width = length + 2

    # 엑셀 파일로 응답
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=traffic_sample.xlsx'
    wb.save(response)
    return response

@login_required
def task_action(request):
    if request.method == 'POST':
        selected_task_ids = request.POST.getlist('selected_tasks')
        action = request.POST.get('action')
        next_url = request.POST.get('next', 'rankings:dashboard')  # next 파라미터를 가져옴
        if selected_task_ids:
            tasks = Task.objects.filter(id__in=selected_task_ids)
            if action == 'edit':
                task_ids = ','.join(selected_task_ids)
                return redirect(f"{reverse('rankings:task_update')}?task_ids={task_ids}")
            elif action == 'complete':
                today = timezone.now().date()
                tasks.update(available_end_date=today)
                messages.success(request, "선택한 작업을 완료했습니다.")
            elif action == 'extend':
                for task in tasks:
                    # 새로운 작업 생성
                    new_task = Task.objects.create(
                        product=task.product,
                        category=task.category,
                        keyword=task.keyword,
                        url=task.url,
                        start_rank=task.start_rank,
                        yesterday_rank=task.yesterday_rank,
                        current_rank=task.current_rank,
                        difference_rank=task.difference_rank,
                        status=task.status,
                        memo=task.memo,
                        ticket_count=task.ticket_count,
                        product_name=task.product_name,
                        original_link=task.original_link,
                        original_mid=task.original_mid,
                        traffic=task.traffic,
                        is_completed=task.is_completed,
                        ending_rank=task.ending_rank,
                        available_start_date=task.available_end_date + timedelta(days=1),
                        available_end_date=task.available_end_date + timedelta(days=10),
                        is_extended=True,
                        original_task=task,
                    )
                messages.success(request, "선택한 작업을 10일 연장했습니다.")
            elif action == 'undo_extend':
                # 연장된 작업을 찾아서 삭제
                extended_tasks = Task.objects.filter(original_task__in=tasks, is_extended=True)
                extended_tasks.delete()
                messages.success(request, "선택한 작업의 연장을 취소했습니다.")
            elif action == 'delete':
                tasks.delete()
                messages.success(request, "선택한 작업을 삭제했습니다.")
        else:
            messages.warning(request, "작업을 선택해주세요.")
        return redirect(next_url)

def task_extend(request):
    if request.method == 'POST':
        task_ids = request.POST.get('task_ids').split(',')
        new_end_date = request.POST.get('new_end_date')
        if new_end_date:
            Task.objects.filter(id__in=task_ids).update(available_end_date=new_end_date)
            messages.success(request, "선택한 작업의 종료일자를 연장했습니다.")
        else:
            messages.warning(request, "새로운 종료일자를 입력해주세요.")
        return redirect('rankings:dashboard')
    else:
        task_ids = request.GET.get('task_ids').split(',')
        tasks = Task.objects.filter(id__in=task_ids)
        return render(request, 'rankings/task_extend.html', {'tasks': tasks, 'task_ids': ','.join(task_ids)})

def product_select(request):
    task_id = request.GET.get('task_id')
    products = Product.objects.all()
    return render(request, 'rankings/product_select.html', {'products': products, 'task_id': task_id})

@login_required
def task_edit(request):
    if request.method == 'POST':
        selected_task_ids = request.POST.getlist('selected_tasks')
        if not selected_task_ids:
            messages.error(request, '수정할 작업을 선택해주세요.')
            return redirect('rankings:task_list')
        selected_task_ids = task_ids.split(',')
        tasks = Task.objects.filter(id__in=selected_task_ids)
        traffics = Traffic.objects.all()
        context = {'tasks': tasks, 'traffics': traffics}
        return render(request, 'rankings/task_edit.html', context)
    else:
        return redirect('rankings:task_list')  # GET 요청 시 적절한 페이지로 리디렉션


def update_rankings():
    today = timezone.now().date()
    tasks = Task.objects.filter(is_completed=False, available_start_date__lte=today)

    for task in tasks:
        try:
            # 순위 업데이트 로직
            current_rank = get_naver_rank(task.keyword.name, task.url)
            task.yesterday_rank = task.current_rank
            task.current_rank = current_rank
            task.difference_rank = (task.yesterday_rank - task.current_rank) if task.yesterday_rank else 0
        except Exception as e:
            print(f"Error updating task {task.id}: {e}")
            continue

        # 완료된 작업 업데이트
        if today > task.available_end_date:
            if not task.is_completed:  # 이미 완료된 작업은 재처리하지 않음
                task.is_completed = True
                task.ending_rank = task.current_rank

        task.save()



@login_required
def update_all_rankings(request):
    if request.method == 'POST':
        tasks = Task.objects.filter( available_end_date__gte=timezone.now().date())
        for task in tasks:
            try:
                current_rank = get_naver_rank(task.keyword.name, task.url)
                if current_rank == -1 or current_rank > 1000:
                    current_rank = None
                difference_rank = (
                    (task.current_rank - current_rank)
                    if task.current_rank is not None and current_rank is not None
                    else None
                )
                task.yesterday_rank = task.current_rank
                task.current_rank = current_rank
                task.difference_rank = difference_rank
                task.last_checked_date = timezone.now()
                task.save()
                # Ranking 모델에 저장
                Ranking.objects.create(
                    product=task.product,
                    keyword=task.keyword,
                    rank=current_rank,
                    date_time=timezone.now(),
                    task=task,  # task 필드 추가

                )
            except Exception as e:
                logger.error(f"작업 ID {task.id}의 순위 업데이트 중 오류 발생: {e}")
                messages.error(request, f"작업 ID {task.id}의 순위 조회 중 오류가 발생했습니다.")
        messages.success(request, "모든 작업의 순위가 업데이트되었습니다.")
        return redirect('rankings:dashboard')
    else:
        return redirect('rankings:dashboard')
    
def traffic_create(request):
    if request.method == 'POST':
        form = TrafficForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '트래픽이 성공적으로 등록되었습니다.')
            return redirect('rankings:traffic_list')
    else:
        form = TrafficForm()
    return render(request, 'rankings/traffic_register.html', {'form': form})


def traffic_update(request, pk):
    traffic = get_object_or_404(Traffic, pk=pk)
    if request.method == 'POST':
        form = TrafficForm(request.POST, instance=traffic)
        if form.is_valid():
            form.save()
            messages.success(request, '트래픽이 성공적으로 수정되었습니다.')
            return redirect('rankings:traffic_list')
    else:
        form = TrafficForm(instance=traffic)
    return render(request, 'rankings/traffic_register.html', {'form': form})


from django.contrib.auth.decorators import login_required

@login_required
def traffic_cost_summary(request):
    # 필터링을 위한 GET 파라미터 가져오기
    selected_product_id = request.GET.get('product')
    selected_traffic_id = request.GET.get('traffic')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # 날짜 범위 설정
    today = datetime.today().date()  # 오늘 날짜
    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=14)
        end_date = today + timedelta(days=14)

    date_range = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]

    # 각 날짜별로 비용을 계산할 딕셔너리 생성
    date_costs = {date: 0 for date in date_range}

    # 현재 활성화된 작업 가져오기 (필터 적용)
    tasks = Task.objects.filter(
        available_start_date__lte=end_date,
        available_end_date__gte=start_date,
    )

    if selected_product_id:
        tasks = tasks.filter(product_id=selected_product_id)
    if selected_traffic_id:
        tasks = tasks.filter(traffic_id=selected_traffic_id)

    total_cost = 0  # 총 비용 초기화

    for task in tasks:
        # 작업의 실제 시작일과 종료일 계산
        task_start = max(task.available_start_date, start_date)
        task_end = min(task.available_end_date, end_date)

        # 작업에 연결된 트래픽 가져오기
        traffic = task.traffic
        if traffic and traffic.price and traffic.days:
            # 트래픽의 일일 비용 계산
            total_days = traffic.days
            daily_cost = traffic.price / total_days
            daily_cost = int(daily_cost)  # 소수점 이하 절삭

            # 작업 기간 내의 각 날짜에 비용 누적
            for n in range((task_end - task_start).days + 1):
                current_date = task_start + timedelta(days=n)
                if current_date in date_costs:
                    date_costs[current_date] += daily_cost
                    total_cost += daily_cost  # 총 비용에 일일 비용 추가

    # 날짜별 비용 데이터를 리스트로 변환하여 날짜 순으로 정렬
    date_costs = sorted(date_costs.items())

    # 날짜와 비용을 각각의 리스트로 분리
    date_labels = [date.strftime('%Y-%m-%d') for date, _ in date_costs]
    cost_data = [cost for _, cost in date_costs]

    # JSON 형식으로 변환
    date_labels_json = json.dumps(date_labels)
    cost_data_json = json.dumps(cost_data)

    # 모든 상품과 트래픽을 가져오기 (필터 선택을 위해)
    products = Product.objects.all()
    traffics = Traffic.objects.all()

    context = {
        'date_labels_json': date_labels_json,
        'cost_data_json': cost_data_json,
        'products': products,
        'traffics': traffics,
        'selected_product_id': int(selected_product_id) if selected_product_id else '',
        'selected_traffic_id': int(selected_traffic_id) if selected_traffic_id else '',
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'total_cost': total_cost,
    }
    return render(request, 'rankings/traffic_cost_summary.html', context)


# 로그인한 사용자만 접근 가능
# @login_required
# def my_data_view(request):
#     # 로그인한 사용자 본인의 데이터만 가져오기
#     user_data = MyModel.objects.all()
#     return render(request, 'my_template.html', {'user_data': user_data})

@login_required
def dashboard_view(request):
    products = Product.objects.all()
    traffic_data = Traffic.objects.all()
    # 기타 필요한 데이터 조회
    context = {
        'products': products,
        'traffic_data': traffic_data,
        # 기타 데이터
    }
    return render(request, 'dashboard.html', context)

@login_required
def product_list_view(request):
    if request.method == "POST":
        selected_products = request.POST.getlist('selected_products')
        if not selected_products:
            messages.error(request, "상품을 선택해주세요.")
            return redirect('rankings:product_list')

        if 'register_traffic' in request.POST:
            # 트래픽 등록 로직
            pass
        elif 'delete_products' in request.POST:
            # 선택한 상품 삭제 로직
            Product.objects.filter(id__in=selected_products).delete()
            messages.success(request, "선택한 상품을 삭제했습니다.")
            return redirect('rankings:product_list')

    # GET 요청 처리
    products_list = Product.objects.all()

    # 페이지네이션 설정
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 100)
    per_page_options = [100, 300, 500, 1000]

    # per_page 값 검증
    try:
        per_page = int(per_page)
        if per_page not in per_page_options:
            per_page = 100
    except ValueError:
        per_page = 100

    paginator = Paginator(products_list, per_page)

    try:
        products = paginator.page(page)
    except PageNotAnInteger:
        # 페이지 번호가 정수가 아니면 첫 번째 페이지를 보여줍니다.
        products = paginator.page(1)
    except EmptyPage:
        # 페이지 번호가 범위를 벗어나면 마지막 페이지를 보여줍니다.
        products = paginator.page(paginator.num_pages)

    context = {
        'products': products,
        'per_page_options': per_page_options,
        'selected_per_page': per_page,
        'traffics': Traffic.objects.all(),  # Traffic 객체들을 추가
    }

    return render(request, 'rankings/product_list.html', context)

@login_required
def traffic_list(request):
    if request.method == 'POST':
        selected_traffics = request.POST.getlist('selected_traffics')
        if not selected_traffics:
            messages.error(request, "트래픽을 선택해주세요.")
            return redirect('rankings:traffic_list')

        if 'edit_traffics' in request.POST:
            # 트래픽 수정 로직
            return redirect('rankings:traffic_bulk_edit')  # 필요한 경우 수정
        elif 'delete_traffics' in request.POST:
            # 선택한 트래픽 삭제 로직
            Traffic.objects.filter(id__in=selected_traffics).delete()
            messages.success(request, "선택한 트래픽을 삭제했습니다.")
            return redirect('rankings:traffic_list')

    # GET 요청 처리
    traffics_list = Traffic.objects.all()

    # 페이지네이션 설정
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 100)
    per_page_options = [100, 300, 500, 1000]

    # per_page 값 검증
    try:
        per_page = int(per_page)
        if per_page not in per_page_options:
            per_page = 100
    except ValueError:
        per_page = 100

    paginator = Paginator(traffics_list, per_page)

    try:
        traffics = paginator.page(page)
    except PageNotAnInteger:
        traffics = paginator.page(1)
    except EmptyPage:
        traffics = paginator.page(paginator.num_pages)

    context = {
        'traffics': traffics,
        'per_page_options': per_page_options,
        'selected_per_page': per_page,
    }
    return render(request, 'rankings/traffic_list.html', context)

@login_required
def product_create_view(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.user = request.user  # 현재 로그인한 사용자 지정
            product.save()
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'product_form.html', {'form': form})

@login_required
def completed_tasks_delete(request):
    if request.method == 'POST':
        selected_task_ids = request.POST.getlist('selected_tasks')
        if selected_task_ids:
            Task.objects.filter(id__in=selected_task_ids).delete()
            messages.success(request, "선택한 완료된 작업을 삭제했습니다.")
        else:
            messages.warning(request, "삭제할 작업을 선택해주세요.")
    return redirect('rankings:completed_tasks_list')

@login_required
def my_page(request):
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        if 'modify' in request.POST:
            # '수정' 버튼 클릭 시
            form = UserProfileForm(instance=user_profile)
            settings_completed = False
        else:
            # 폼 제출 시
            form = UserProfileForm(request.POST, instance=user_profile)
            if form.is_valid():
                form.save()
                messages.success(request, "셋팅이 완료되었습니다.")
                return redirect('rankings:my_page')
            else:
                messages.error(request, "입력한 정보를 확인해주세요.")
                settings_completed = False
    else:
        settings_completed = bool(user_profile.naver_client_id and user_profile.naver_client_secret)
        form = None if settings_completed else UserProfileForm(instance=user_profile)

    # 저장 후에도 NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET를 템플릿에 전달
    client_id = user_profile.naver_client_id if user_profile.naver_client_id else ''
    client_secret = user_profile.naver_client_secret if user_profile.naver_client_secret else ''

    context = {
        'form': form,
        'settings_completed': settings_completed,
        'client_id': client_id,
        'client_secret': client_secret,
    }
    return render(request, 'rankings/my_page.html', context)

from django.db.models import Q



@login_required
def ad_single_summary(request):
    ads = Ad.objects.all()

    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    today = date.today()
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today - timedelta(days=30)
            end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today

    # 기간 필터링 적용
    ads = ads.filter(
        Q(start_date__lte=end_date, end_date__gte=start_date) |
        Q(start_date__gte=start_date, end_date__lte=end_date)
    )

    # 계산 로직 구현
    ad_data = []
    for ad in ads:
        # 필요한 계산 수행
        profit = ad.margin - ad.cost
        margin_rate = (ad.margin / ad.sales) * 100 if ad.sales else 0
        profit_rate = (profit / ad.sales) * 100 if ad.sales else 0
        roas = (ad.sales / ad.cost) * 100 if ad.cost else 0
        roi = (profit / ad.cost) * 100 if ad.cost else 0

        ad_data.append({
            'id': ad.id,
            'start_date': ad.start_date,
            'end_date': ad.end_date,
            'channel': ad.channel,
            'ad_name': ad.name,
            'category': ad.category,
            'product_name': ad.product,
            'sales': ad.sales,
            'margin': ad.margin,
            'cost': ad.cost,
            'profit': profit,
            'margin_rate': margin_rate,
            'profit_rate': profit_rate,
            'roas': roas,
            'roi': roi,
            'memo': ad.memo,
            'page_link': ad.page_link,
            'company': ad.company,
        })

    # 페이지네이션 설정
    page = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', 10)
    per_page_options = [10, 30, 50, 100]

    # per_page 값 검증
    try:
        per_page = int(per_page)
        if per_page not in per_page_options:
            per_page = 10
    except ValueError:
        per_page = 10

    paginator = Paginator(ad_data, per_page)

    try:
        ads_page = paginator.page(page)
    except PageNotAnInteger:
        ads_page = paginator.page(1)
    except EmptyPage:
        ads_page = paginator.page(paginator.num_pages)

    context = {
        'ads': ads_page,
        'start_date': start_date,
        'end_date': end_date,
        'per_page_options': per_page_options,
        'selected_per_page': per_page,
    }
    return render(request, 'rankings/ad_single_summary.html', context)



@login_required
def ad_create(request):
    if request.method == 'POST':
        if 'upload_excel' in request.POST:
            # 엑셀 업로드 처리
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                messages.error(request, "엑셀 파일을 선택해주세요.")
                return redirect('rankings:ad_create')

            try:
                wb = openpyxl.load_workbook(excel_file)
                sheet = wb.active
                ads_data = []
                error_occurred = False  # 에러 발생 여부를 추적
                for idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):  # 헤더 제외
                    # 엑셀 파일의 열 순서에 따라 데이터 매핑
                    start_date = row[0]
                    end_date = row[1]
                    channel = row[2]
                    name = row[3]
                    category = row[4]
                    product = row[5]
                    sales = row[6]
                    margin = row[7]
                    cost = row[8]
                    memo = row[9]
                    page_link = row[10]
                    company = row[11]

                    # 필수 값 검증
                    missing_fields = []
                    if not start_date:
                        missing_fields.append('시작일')
                    if not end_date:
                        missing_fields.append('종료일')
                    if not channel:
                        missing_fields.append('채널')
                    if not name:
                        missing_fields.append('광고명')
                    if missing_fields:
                        error_message = f"{idx}행: 필수 필드 누락 - {', '.join(missing_fields)}"
                        messages.error(request, error_message)
                        error_occurred = True
                        continue  # 다음 행으로 이동

                    # 날짜 형식 변환 및 유효성 검사
                    try:
                        if isinstance(start_date, datetime):
                            start_date = start_date.date()
                        elif isinstance(start_date, date):
                            pass
                        elif isinstance(start_date, str):
                            # 여러 날짜 형식 시도
                            for fmt in ('%m/%d/%y', '%Y-%m-%d', '%Y/%m/%d', '%m-%d-%Y'):
                                try:
                                    start_date = datetime.strptime(start_date, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            else:
                                raise ValueError
                        else:
                            raise ValueError
                    except ValueError:
                        error_message = f"{idx}행: 시작일의 날짜 형식이 올바르지 않습니다."
                        messages.error(request, error_message)
                        error_occurred = True
                        continue  # 다음 행으로 이동

                    try:
                        if isinstance(end_date, datetime):
                            end_date = end_date.date()
                        elif isinstance(end_date, date):
                            pass
                        elif isinstance(end_date, str):
                            # 여러 날짜 형식 시도
                            for fmt in ('%m/%d/%y', '%Y-%m-%d', '%Y/%m/%d', '%m-%d-%Y'):
                                try:
                                    end_date = datetime.strptime(end_date, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            else:
                                raise ValueError
                        else:
                            raise ValueError
                    except ValueError:
                        error_message = f"{idx}행: 종료일의 날짜 형식이 올바르지 않습니다."
                        messages.error(request, error_message)
                        error_occurred = True
                        continue  # 다음 행으로 이동

                    # 날짜를 문자열로 변환 (YYYY-MM-DD 형식)
                    start_date_str = start_date.strftime('%Y-%m-%d')
                    end_date_str = end_date.strftime('%Y-%m-%d')

                    # 광고 데이터를 리스트에 추가
                    ads_data.append({
                        'start_date': start_date_str,
                        'end_date': end_date_str,
                        'channel': channel,
                        'name': name,
                        'category': category,
                        'product': product,
                        'sales': sales if sales else '',
                        'margin': margin if margin else '',
                        'cost': cost if cost else '',
                        'memo': memo or '',
                        'page_link': page_link or '',
                        'company': company or '',
                    })
                if error_occurred:
                    # 오류가 발생한 경우, ads_data와 함께 폼을 렌더링하여 사용자에게 오류를 표시
                    return render(request, 'rankings/ad_form.html', {'ads_data': ads_data, 'today': timezone.now().strftime('%Y-%m-%d')})
                else:
                    # 오류가 없으면 ads_data를 컨텍스트에 전달하여 폼에 표시
                    return render(request, 'rankings/ad_form.html', {'ads_data': ads_data, 'today': timezone.now().strftime('%Y-%m-%d')})
            except Exception as e:
                messages.error(request, f"엑셀 파일 처리 중 오류 발생: {str(e)}")
                return render(request, 'rankings/ad_form.html', {'today': timezone.now().strftime('%Y-%m-%d')})

        else:
            # 폼 데이터 처리
            start_dates = request.POST.getlist('start_date')
            end_dates = request.POST.getlist('end_date')
            channels = request.POST.getlist('channel')
            names = request.POST.getlist('name')
            categories = request.POST.getlist('category')
            products = request.POST.getlist('product')
            sales_list = request.POST.getlist('sales')
            margins = request.POST.getlist('margin')
            costs = request.POST.getlist('cost')
            memos = request.POST.getlist('memo')
            page_links = request.POST.getlist('page_link')
            companies = request.POST.getlist('company')
            print("start_dates:", start_dates)
            print("end_dates:", end_dates)
            print("channels:", channels)
            print("names:", names)
            if not names:
                messages.error(request, "등록할 광고 데이터가 없습니다.")
                return redirect('rankings:ad_create')

            # 모든 광고 항목을 저장
            error_occurred = False
            for i in range(len(names)):
                # 필수 값 검증
                if not (start_dates[i] and end_dates[i] and channels[i] and names[i]):
                    messages.error(request, f"{i + 1}번째 행의 필수 값을 모두 입력해주세요.")
                    error_occurred = True
                    continue  # 필수 값이 없으면 건너뜁니다

                # 데이터 타입 변환 및 유효성 검사
                try:
                    sales = float(sales_list[i]) if sales_list[i] else 0
                    margin = float(margins[i]) if margins[i] else 0
                    cost = float(costs[i]) if costs[i] else 0
                except ValueError:
                    messages.error(request, f"{i + 1}번째 행의 숫자 필드에 올바른 값을 입력해주세요.")
                    error_occurred = True
                    continue  # 값이 유효하지 않으면 건너뜁니다

                # 광고 생성
                Ad.objects.create(
                    start_date=start_dates[i],
                    end_date=end_dates[i],
                    channel=channels[i],
                    name=names[i],
                    category=categories[i] or '',
                    product=products[i] or '',
                    sales=sales,
                    margin=margin,
                    cost=cost,
                    memo=memos[i] or '',
                    page_link=page_links[i] or '',
                    company=companies[i] or '',
                )
            if error_occurred:
                messages.error(request, "일부 광고 항목이 등록되지 않았습니다. 오류를 확인해주세요.")
                # 입력된 데이터를 폼에 다시 표시하기 위해 컨텍스트에 전달
                ads_data = []
                for i in range(len(names)):
                    ads_data.append({
                        'start_date': start_dates[i],
                        'end_date': end_dates[i],
                        'channel': channels[i],
                        'name': names[i],
                        'category': categories[i],
                        'product': products[i],
                        'sales': sales_list[i],
                        'margin': margins[i],
                        'cost': costs[i],
                        'memo': memos[i],
                        'page_link': page_links[i],
                        'company': companies[i],
                    })
                return render(request, 'rankings/ad_form.html', {'ads_data': ads_data, 'today': timezone.now().strftime('%Y-%m-%d')})
            else:
                messages.success(request, "광고를 성공적으로 등록했습니다.")
                return redirect('rankings:ad_single_summary')
    
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        return render(request, 'rankings/ad_form.html', {'today': today})


     
@login_required
def ad_update(request, pk):
    ad = get_object_or_404(Ad, pk=pk)
    if request.method == 'POST':
        form = AdForm(request.POST, instance=ad)
        if form.is_valid():
            form.save()
            messages.success(request, "광고가 성공적으로 수정되었습니다.")
            return redirect('rankings:ad_single_summary')
    else:
        form = AdForm(instance=ad)
    return render(request, 'rankings/ad_form.html', {'form': form})

# views.py

@login_required
def ad_bulk_edit(request):
    AdFormSet = modelformset_factory(Ad, form=AdForm, extra=0)
    if request.method == 'POST':
        if 'edit_ads' in request.POST:
            # 선택된 광고 IDs를 가져옵니다.
            selected_ids = request.POST.getlist('ad_ids')
            if not selected_ids:
                messages.error(request, "수정할 광고를 선택해주세요.")
                return redirect('rankings:ad_single_summary')
            ads = Ad.objects.filter(id__in=selected_ids)
            # **각 필드의 초기값을 소수점 제거하여 설정**
            initial_data = []
            for ad in ads:
                initial_data.append({
                    'id': ad.id,
                    'start_date': ad.start_date,
                    'end_date': ad.end_date,
                    'channel': ad.channel,
                    'name': ad.name,
                    'category': ad.category,
                    'product': ad.product,
                    'sales': int(ad.sales),
                    'margin': int(ad.margin),
                    'cost': int(ad.cost),
                    'memo': ad.memo,
                    'page_link': ad.page_link,
                    'company': ad.company,
                })
            formset = AdFormSet(queryset=ads, initial=initial_data)
        else:
            # 폼셋이 제출된 경우
            formset = AdFormSet(request.POST)
            if formset.is_valid():
                # 저장하기 전에 소수점 이하 자릿수를 제거합니다.
                instances = formset.save(commit=False)
                for instance in instances:
                    instance.sales = int(instance.sales)
                    instance.margin = int(instance.margin)
                    instance.cost = int(instance.cost)
                    instance.save()
                messages.success(request, "선택한 광고가 성공적으로 수정되었습니다.")
                return redirect('rankings:ad_single_summary')
            else:
                messages.error(request, "폼에 오류가 있습니다. 확인해주세요.")
    else:
        messages.error(request, "잘못된 접근입니다.")
        return redirect('rankings:ad_single_summary')
    return render(request, 'rankings/ad_bulk_edit.html', {'formset': formset})




@login_required
def ad_delete(request, pk):
    # `Ad` 모델에서 `pk`에 해당하는 객체 가져오기
    ad = get_object_or_404(Ad, pk=pk)  # user 필터링은 필요에 따라 추가

    # POST 요청이 확인되면 객체 삭제
    if request.method == 'POST':
        ad.delete()
        messages.success(request, '광고가 성공적으로 삭제되었습니다.')
        return redirect('rankings:ad_single_summary')  # 리디렉션할 URL 네임스페이스 확인 필요

    # 삭제 확인을 위한 템플릿 렌더링
    return render(request, 'rankings/ad_confirm_delete.html', {'ad': ad})

def ad_upload(request):
    if request.method == 'POST':
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES['file']
            df = pd.read_excel(excel_file)

            # 데이터프레임의 각 행을 Ad 모델로 저장
            for index, row in df.iterrows():
                Ad.objects.create(
                    name=row['이름'],
                    start_date=row['시작일자'],
                    end_date=row['종료일자'],
                    # 나머지 필드들에 맞게 매핑
                    # 예: product=row['상품명'], cost=row['비용'], ...
                )
            return redirect('rankings:ad_single_summary')
    else:
        form = ExcelUploadForm()
    return render(request, 'rankings/ad_upload.html', {'form': form})

@login_required
def ad_delete_multiple(request):
    if request.method == 'POST':
        ad_ids = request.POST.getlist('ad_ids')
        if ad_ids:
            ads_to_delete = Ad.objects.filter(id__in=ad_ids)
            ads_to_delete.delete()
            messages.success(request, f"{len(ads_to_delete)}개의 광고가 삭제되었습니다.")
        else:
            messages.error(request, "삭제할 광고를 선택하세요.")
    return redirect('rankings:ad_single_summary')

@login_required
def download_sample_excel(request):
    # 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active

    # 헤더 설정
    headers = [
        '시작일', '종료일', '채널', '광고명', '카테고리', '상품명',
        '매출', '마진', '비용', '메모', '페이지 링크', '업체'
    ]
    ws.append(headers)

    # 데이터 추가
    data = [
        '11/1/24', '11/10/24', '인스타', '공구', '가구', '소파',
        1000000, 500000, 300000, '메모 내용', 'http://example.com', '업체A'
    ]
    ws.append(data)

    # 열 너비 조정 및 정렬
    for column_cells in ws.columns:
        length = max(len(str(cell.value)) for cell in column_cells)
        column_letter = column_cells[0].column_letter
        ws.column_dimensions[column_letter].width = length + 2
        for cell in column_cells:
            cell.alignment = Alignment(horizontal='center', vertical='center')

    # 엑셀 파일로 응답
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=sample_ad_data.xlsx'
    wb.save(response)
    return response





def custom_404(request, exception):
    return render(request, 'errors/404.html', status=404)

def custom_500(request):
    return render(request, 'errors/500.html', status=500)



# views.py

from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import localtime

def get_ranking_data(request):
    task_id = request.GET.get('task_id')
    if not task_id:
        return JsonResponse({'error': 'Task ID is required.'}, status=400)

    try:
        task = Task.objects.get(id=task_id)
    except Task.DoesNotExist:
        return JsonResponse({'error': 'Task not found.'}, status=404)

    rankings = Ranking.objects.filter(task=task).order_by('-date_time')

    # 시작 순위 가져오기
    start_rank = task.start_rank if task.start_rank else 1000

    rankings_list = []
    previous_rank = None
    for ranking in rankings:
        # 날짜와 시간을 한국 시간대로 변환
        local_date_time = localtime(ranking.date_time)
        date_time_str = local_date_time.strftime('%Y-%m-%d %H:%M:%S')

        rank = ranking.rank if ranking.rank else 1000

        # 등락폭 계산
        if previous_rank is not None:
            difference = rank - previous_rank
        else:
            difference = 0

        # 순위 변동을 숫자로만 반환
        # 양수: 순위가 내려감 (숫자 커짐)
        # 음수: 순위가 올라감 (숫자 작아짐)
        difference_value = difference

        # 시작 대비 등락폭 계산
        start_difference = rank - start_rank

        rankings_list.append({
            'date_time': date_time_str,
            'keyword': ranking.keyword.name,
            'rank': rank,
            'difference': difference_value,           # 숫자 값으로만 반환
            'start_difference': start_difference,     # 숫자 값으로만 반환
        })

        previous_rank = rank

    return JsonResponse({'rankings': rankings_list})


@login_required
def download_selected_products_excel(request):
    product_ids = request.GET.get('product_ids')
    if not product_ids:
        messages.error(request, '상품이 선택되지 않았습니다.')
        return redirect('rankings:product_list')

    product_ids = product_ids.split(',')
    products = Product.objects.filter(id__in=product_ids)

    # 엑셀 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '작업 등록'

    # 헤더 작성
    headers = ['번호', '상품명', '카테고리', '순위조회키워드', 'URL 타입', 'URL', '메모', '트래픽명', '이용권 수', '이용가능 시작일자', '이용가능 종료일자']
    ws.append(headers)

    # 데이터 작성
    for idx, product in enumerate(products, start=1):
        row = [
            idx,
            product.name,
            product.category,
            product.search_keyword,
            '',  # URL 타입
            '',  # URL
            '',  # 메모
            '',  # 트래픽명
            '',  # 이용권 수
            '',  # 이용가능 시작일자
            '',  # 이용가능 종료일자
        ]
        ws.append(row)

    # 컬럼 너비 조절
    for col_idx, _ in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 20

    # 엑셀 파일 응답
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = 'task_template.xlsx'
    response['Content-Disposition'] = f'attachment; filename={smart_str(filename)}'
    wb.save(response)
    return response

@login_required
def upload_excel_data(request):
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, '엑셀 파일을 선택해주세요.')
            return redirect('rankings:product_list')

        try:
            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active

            # 헤더 추출
            headers = [str(cell.value).strip() if cell.value else '' for cell in ws[1]]

            # 기대하는 헤더 목록
            expected_headers = ['번호', '상품명', '카테고리', '순위조회키워드', 'URL 타입', 'URL', '메모', '트래픽명', '이용권 수', '이용가능 시작일자', '이용가능 종료일자']

            # 헤더 검증
            if headers != expected_headers:
                messages.error(request, '엑셀 파일의 헤더가 올바르지 않습니다. 다운로드한 템플릿을 사용해주세요.')
                return redirect('rankings:product_list')

            # 데이터 추출
            task_data = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                data = dict(zip(headers, row))
                task_data.append(data)

            if not task_data:
                messages.error(request, '엑셀 파일에 데이터가 없습니다.')
                return redirect('rankings:product_list')

            # 작업 등록 페이지를 직접 렌더링
            products = []
            initial_data = {}
            for idx, data in enumerate(task_data):
                product_name = data.get('상품명')
                if not product_name:
                    continue  # 상품명이 없으면 건너뜁니다.
                try:
                    product = Product.objects.get(name=product_name)
                except Product.DoesNotExist:
                    continue
                products.append(product)
                product_id = product.id
                initial_data[product_id] = {
                    'keyword': data.get('순위조회키워드', ''),
                    'url_type': data.get('URL 타입', ''),
                    'url': data.get('URL', ''),
                    'memo': data.get('메모', ''),
                    'product_name': product_name,
                    'traffic_id': '',  # 필요 시 추가
                    'ticket_count': data.get('이용권 수', ''),
                    'available_start_date': data.get('이용가능 시작일자', ''),
                    'available_end_date': data.get('이용가능 종료일자', ''),
                }

            traffics = Traffic.objects.all()
            context = {
                'products': products,
                'traffics': traffics,
                'initial_data': initial_data,
            }
            return render(request, 'rankings/task_register.html', context)
        except Exception as e:
            messages.error(request, f'엑셀 파일 처리 중 오류가 발생했습니다: {str(e)}')
            return redirect('rankings:product_list')
    else:
        messages.error(request, '잘못된 요청입니다.')
        return redirect('rankings:product_list')



    
@login_required
def task_register_from_excel(request):
    if request.method == 'POST':
        task_data_json = request.POST.get('task_data')
        if not task_data_json:
            return JsonResponse({'success': False, 'error': '엑셀 데이터를 찾을 수 없습니다.'})

        try:
            task_data = json.loads(task_data_json)
            request.session['uploaded_task_data'] = task_data
            return JsonResponse({'success': True})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': '엑셀 데이터 파싱 중 오류가 발생했습니다.'})

    else:
        task_data = request.session.get('uploaded_task_data')
        if not task_data:
            messages.error(request, '엑셀 데이터를 찾을 수 없습니다.')
            return redirect('rankings:product_list')

        # task_data를 사용하여 products와 initial_data 구성
        products = []
        initial_data = {}
        for idx, data in enumerate(task_data):
            product_name = data.get('상품명')
            if not product_name:
                continue  # 상품명이 없으면 건너뜁니다.
            try:
                product = Product.objects.get(name=product_name)
            except Product.DoesNotExist:
                continue
            products.append(product)
            product_id = product.id
            initial_data[product_id] = {
                'keyword': data.get('순위조회키워드', ''),
                'url_type': data.get('URL 타입', ''),
                'url': data.get('URL', ''),
                'memo': data.get('메모', ''),
                'product_name': product_name,
                'traffic_id': '',  # 필요 시 추가
                'ticket_count': data.get('이용권 수', ''),
                'available_start_date': data.get('이용가능 시작일자', ''),
                'available_end_date': data.get('이용가능 종료일자', ''),
            }

        traffics = Traffic.objects.all()
        context = {
            'products': products,
            'traffics': traffics,
            'initial_data': initial_data,
        }
        return render(request, 'rankings/task_register.html', context)
