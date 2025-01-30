# views.py
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.shortcuts import render,redirect,get_object_or_404
from django.db.models import Q
from decouple import config
from django.utils.dateparse import parse_date

from .api_clients import (
    NAVER_ACCOUNTS,
    COUPANG_ACCOUNTS,
    fetch_naver_qna_templates,
    fetch_coupang_inquiries,
    save_naver_inquiries_to_db,
    save_coupang_inquiries_to_db,
    put_naver_qna_answer,
    put_coupang_inquiry_answer,
    fetch_coupang_center_inquiries,
    fetch_naver_center_inquiries,
    save_center_naver_inquiries_to_db,
    save_center_coupang_inquiries_to_db,
    put_naver_qna_center_answer,
)
from .utils import send_inquiry_to_dooray_webhook  
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from datetime import timedelta
import logging
from .models import Inquiry,CenterInquiry
from .rag_search import generate_gpt_answer

from django.contrib import messages
import openai

import json

logger = logging.getLogger(__name__)
# Inquiry 모델이 있다고 가정합니다.
# from .models import Inquiry

STORE_LINK_PREFIX = {
    "니뜰리히": "https://smartstore.naver.com/maimaimy/products/",
    "수비다": "https://smartstore.naver.com/subida_outdoor/products/",
    "노는개최고양": "https://smartstore.naver.com/cunsik/products/",
    "아르빙": "https://smartstore.naver.com/arving/products/",
    "A00291106":"https://www.coupang.com/vp/products/",
    "A00800631":"https://www.coupang.com/vp/products/",
}


def update_inquiries(request):
    """
    하나의 뷰에서 platform=all 이면 네이버+쿠팡 전부 업데이트
    (기존 account_info 관련 에러 제거: 내부에서 loops all)
    """
    logger.debug("[update_inquiries] --- START ---")

    platform = request.GET.get('platform', '')  # "naver" / "coupang" / "all"
    filter_status = request.GET.get('status', '')  # 'pending' or 'answered'
    logger.debug(f"[update_inquiries] GET => platform={platform}, status={filter_status}")

    # answered: True => answered, False => pending, None => all
    answered = None
    if filter_status == 'pending':
        answered = False
    elif filter_status == 'answered':
        answered = True

        # answered를 answeredType으로 변환
    if answered is True:
        answered_type = "ANSWERED"
    elif answered is False:
        answered_type = "NOANSWER"
    else:
        answered_type = "ALL"
        
    # 1) 네이버만
    if platform == 'naver':
        logger.debug("[update_inquiries] => NAVER 전체 계정")
        success, merged_data = fetch_naver_qna_templates(answered=answered)
        if success:
            saved_objs = save_naver_inquiries_to_db(merged_data)
            logger.info(f"[update_inquiries] NAVER saved={len(saved_objs)}")
        else:
            logger.error(f"[update_inquiries] NAVER 실패: {merged_data}")

    # 2) 쿠팡만
    elif platform == 'coupang':
        logger.debug("[update_inquiries] => 쿠팡 전체 계정")
        success, merged_data = fetch_coupang_inquiries(answered=answered)
        if success:
            saved_objs = save_coupang_inquiries_to_db(merged_data)
            logger.info(f"[update_inquiries] 쿠팡 saved={len(saved_objs)}")
        else:
            logger.error(f"[update_inquiries] 쿠팡 실패: {merged_data}")

    # 3) 네이버+쿠팡
    elif platform == 'all':
        logger.debug("[update_inquiries] => 네이버+쿠팡 둘 다")

        # (A) 네이버
        success_n, data_n = fetch_naver_qna_templates(answered=answered)
        if success_n:
            saved_n = save_naver_inquiries_to_db(data_n)
            logger.info(f"[update_inquiries] NAVER all => saved={len(saved_n)}")
        else:
            logger.error(f"[update_inquiries] NAVER 실패: {data_n}")

        # (B) 쿠팡
        success_c, data_c = fetch_coupang_inquiries(
            start_date=None,   # or your default
            end_date=None,     # or your default
            answeredType=answered_type,
            pageNum=1,
            pageSize=10
        )
        if success_c:
            saved_c = save_coupang_inquiries_to_db(data_c)
            logger.info(f"[update_inquiries] COUPANG all => saved={len(saved_c)}")
        else:
            logger.error(f"[update_inquiries] 쿠팡 실패: {data_c}")

    else:
        logger.warning(f"[update_inquiries] Unknown platform={platform}")

    logger.debug("[update_inquiries] --- END ---")
    return redirect('cs_management:inquiry_product_list')


def inquiry_product_list(request):
    """
    DB 조회 후 템플릿 표시 (검색/필터/미답변 건수/구간 필터)
    """
    # --- GET 파라미터 ---
    search_query = request.GET.get('q', '')
    filter_status = request.GET.get('status', '')        # 'pending' or 'answered'
    time_range = request.GET.get('range', '')            # '24h', '24_72h', '72_30d'...
    start_date_str = request.GET.get('start_date', '')   # YYYY-MM-DD
    end_date_str = request.GET.get('end_date', '')

    page_number = request.GET.get('page', '1')  # 기본 1페이지

    # --- collapse 열기여부: GET 파라미터가 있으면 True => 펼침 ---
    open_collapse = bool(request.GET)

    # 1) 기본 쿼리 (최신순)
    qs = Inquiry.objects.all().order_by('-created_at_utc')

    # 2) time_range 필터 (구간별 미답변)
    now = timezone.now()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_72h = now - timedelta(hours=72)
    cutoff_30d = now - timedelta(days=30)

    if time_range:
        # range 파라미터가 있으면 미답변으로 제한
        qs = qs.filter(answered=False)
        if time_range == '24h':
            qs = qs.filter(created_at_utc__gte=cutoff_24h)
        elif time_range == '24_72h':
            qs = qs.filter(created_at_utc__lt=cutoff_24h,
                           created_at_utc__gte=cutoff_72h)
        elif time_range == '72_30d':
            qs = qs.filter(created_at_utc__lt=cutoff_72h,
                           created_at_utc__gte=cutoff_30d)
        # 필요시 추가 case 처리

    # 3) 상태 필터
    if filter_status == 'pending':
        qs = qs.filter(answered=False)
    elif filter_status == 'answered':
        qs = qs.filter(answered=True)

    # 4) 검색어 (상품명/내용/작성자)
    if search_query:
        qs = qs.filter(
            Q(product_name__icontains=search_query) |
            Q(content__icontains=search_query) |
            Q(author__icontains=search_query)
        )

    # 5) 날짜 필터 (start_date, end_date)
    from django.utils.dateparse import parse_date
    if start_date_str:
        start_dt = parse_date(start_date_str)
        if start_dt:
            qs = qs.filter(created_at_utc__date__gte=start_dt)
    if end_date_str:
        end_dt = parse_date(end_date_str)
        if end_dt:
            qs = qs.filter(created_at_utc__date__lte=end_dt)

    # 6) 미답변 건수(24h / 24~72h / 72h~30일) 계산
    count_24h = Inquiry.objects.filter(
        answered=False, 
        created_at_utc__gte=cutoff_24h
    ).count()
    count_24_72h = Inquiry.objects.filter(
        answered=False,
        created_at_utc__lt=cutoff_24h,
        created_at_utc__gte=cutoff_72h
    ).count()
    count_72h_30d = Inquiry.objects.filter(
        answered=False,
        created_at_utc__lt=cutoff_72h,
        created_at_utc__gte=cutoff_30d
    ).count()

    # --- (A) 페이지네이션 설정 ---
    paginator = Paginator(qs, 50)  # 페이지당 50개
    page_obj = paginator.get_page(page_number)

    # (B) 커스텀 페이지 범위 계산
    current_page = page_obj.number               # 현재 페이지 번호
    total_pages = page_obj.paginator.num_pages   # 전체 페이지 수

    # 현재 페이지 기준으로 앞뒤 2페이지씩 표시 (최대 5페이지)
    start_index = max(current_page - 2, 1)
    end_index = min(current_page + 2, total_pages)

    # 범위가 5개 미만이면 5개 맞춰주기
    if (end_index - start_index) < 4:
        end_index = min(start_index + 4, total_pages)

    custom_page_range = range(start_index, end_index + 1)

    # 7) 쿼리 결과 -> inquiries 리스트 (page_obj에 있는 50개)
    inquiries = []
    for obj in page_obj:
        date_str = obj.created_at_utc.strftime('%Y-%m-%d %H:%M') if obj.created_at_utc else ""
        status_str = "answered" if obj.answered else "pending"

        # (Optional) 쿠팡 발주서
        order_sheet_str = "No order sheet"
        if obj.order_ids:
            try:
                order_ids_list = json.loads(obj.order_ids)
                if order_ids_list:
                    # 예: CoupangOrderSheet에서 order_id로 가져오기
                    from .models import CoupangOrderSheet
                    first_order_id = order_ids_list[0]
                    c_sheet = CoupangOrderSheet.objects.filter(order_id=first_order_id).first()
                    if c_sheet and c_sheet.raw_json:
                        order_sheet_str = json.dumps(c_sheet.raw_json, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass

        # 대표이미지, 링크
        store_name = obj.store_name or ''
        product_id = obj.product_id
        representative_image = obj.representative_image or ''
        prefix = STORE_LINK_PREFIX.get(store_name, "")
        product_link = f"{prefix}{product_id}" if prefix and product_id else ""

        # [추가 로직] - 최종답변(answer_content)이 비어있으면, gpt_summary를 대신 대입
        final_answer = obj.answer_content.strip() if obj.answer_content else ""
        if not final_answer:
            # DB에 gpt_summary가 있다면 그걸 사용
            if obj.gpt_summary:
                final_answer = f"[GPT 요약]\n{obj.gpt_summary}"

        inquiries.append({
            'id': obj.inquiry_id,
            'product_name': obj.product_name or '',
            'content': obj.content or '',
            'author': obj.author or '',
            'date': date_str,
            'status': status_str,
            'store_name': store_name,
            'order_sheet_raw': order_sheet_str,
            # ↑ 아래 줄만 변경됨:
            'answer_content': final_answer,
            'answer_date': obj.get_answer_date_display(),
            'product_id': product_id,
            'representative_image': representative_image,
            'product_link': product_link,
            'gpt_summary': obj.gpt_summary or '',
            'gpt_recommendation_1': obj.gpt_recommendation_1 or '',
            'gpt_recommendation_2': obj.gpt_recommendation_2 or '',
        })

    # 8) context
    context = {
        'inquiries': inquiries,
        'page_obj': page_obj,
        'custom_page_range': custom_page_range,   # ← 추가됨
        'search_query': search_query,
        'filter_status': filter_status,
        'time_range': time_range,
        'start_date': start_date_str,
        'end_date': end_date_str,

        'count_24h': count_24h,
        'count_24_72h': count_24_72h,
        'count_72h_30d': count_72h_30d,

        'open_collapse': open_collapse,
    }
    return render(request, 'cs_management/inquiry_product.html', context)



def delete_all_inquiries(request):
    """
    Inquiry 모델의 전체 데이터 삭제 뷰
    (주의: 보안/권한 처리 없이 간단히 구현)
    """
    Inquiry.objects.all().delete()
    logger.warning("[delete_all_inquiries] 모든 Inquiry 데이터가 삭제되었습니다.")
    return redirect('cs_management:inquiry_product_list')

@csrf_exempt
@require_POST
def answer_inquiry_unified(request):
    try:
        inquiry_id = request.POST.get('inquiry_id')
        reply_content = request.POST.get('replyContent')

        if not inquiry_id or not reply_content:
            return JsonResponse({'status':'error','message':'Missing parameters'}, status=400)

        # (1) DB에서 Inquiry 찾기 => platform="NAVER" or "COUPANG" or ...
        inq = get_object_or_404(Inquiry, inquiry_id=inquiry_id)

        # (2) 플랫폼별 처리
        if inq.platform == "NAVER":
            # 네이버 로직
            store_name = inq.store_name  # "니뜰리히", "수비다", etc.
            account_info = next((acc for acc in NAVER_ACCOUNTS if store_name in acc['names']), None)
            if not account_info:
                return JsonResponse({'status':'error','message':f"No Naver account for store={store_name}"}, status=404)

            success, result = put_naver_qna_answer(account_info, inq.inquiry_id, reply_content)
            if not success:
                return JsonResponse({'status':'error','message':f'네이버 API 실패: {result}'}, status=400)

        elif inq.platform == "COUPANG":
            store_name = inq.store_name  # 예: "A00291106" or "쿠팡01" 등
            logger.debug(f"[answer_inquiry_unified] (COUPANG) inquiry_id={inq.inquiry_id}, store_name={store_name}")

            account_info = next((acc for acc in COUPANG_ACCOUNTS if store_name in acc['names']), None)
            if not account_info:
                logger.error(f"[answer_inquiry_unified] No Coupang account found for store={store_name}")
                return JsonResponse({'status':'error','message':f"No Coupang account for store={store_name}"}, status=404)

            logger.debug(f"[answer_inquiry_unified] Found account_info => vendor_id={account_info.get('vendor_id')}, wing_id={account_info.get('wing_id')}")

            success, result = put_coupang_inquiry_answer(
                account_info=account_info,
                inquiry_id=inq.inquiry_id,
                content=reply_content,
                reply_by=account_info.get('wing_id')  # "piaar21"
            )

            logger.debug(f"[answer_inquiry_unified] reply_by={store_name} => success={success}, result={result}")

            if not success:
                logger.error(f"[answer_inquiry_unified] 쿠팡 API 실패: {result}")
                return JsonResponse({'status':'error','message':f'쿠팡 API 실패: {result}'}, status=400)

        # (3) DB에 answered, answer_content 저장
        if not inq.answered:
            inq.answered = True
            inq.answered_at = timezone.now()
        else:
            inq.answer_updated_at = timezone.now()

        inq.answer_content = reply_content
        inq.save()

        return JsonResponse({
            'status':'ok',
            'message':'답변 등록/수정 성공',
            'answer_date': inq.get_answer_date_display(),
            'answer_content': inq.answer_content
        })

    except Exception as e:
        logger.exception("answer_inquiry_unified error")
        return JsonResponse({'status':'error','message':str(e)}, status=500)
    

@csrf_exempt
def send_inquiry_webhook_view(request):
    """
    AJAX POST로 넘어온 inquiry_id -> DB조회 -> 웹훅 전송 -> 결과 JSON 응답
    """
    if request.method == "POST":
        inquiry_id = request.POST.get("inquiry_id", "")
        if not inquiry_id:
            return JsonResponse({"status":"error", "message":"inquiry_id가 없습니다."}, status=400)

        try:
            inq = Inquiry.objects.get(inquiry_id=inquiry_id)
        except Inquiry.DoesNotExist:
            return JsonResponse({"status":"error", "message":"해당 문의를 찾을 수 없습니다."}, status=404)

        # store_name, product_name, content
        store_name = inq.store_name or "(알수없음)"
        product_name = inq.product_name or "(알수없음)"
        content = inq.content or ""

        success = send_inquiry_to_dooray_webhook(
            store_name=store_name,
            product_name=product_name,
            content=content
        )
        if success:
            return JsonResponse({"status":"ok", "message":"웹훅 전송 성공"})
        else:
            return JsonResponse({"status":"error", "message":"웹훅 전송 실패"}, status=500)

    return JsonResponse({"status":"error", "message":"Only POST allowed"}, status=405)





def inquiry_gpt_recommend(request, inquiry_id):
    if request.method == "GET":
        # DB에서 answered=False + inquiry_id=~~ 인지? 
        inq = get_object_or_404(Inquiry, inquiry_id=inquiry_id, answered=False)
        user_question = inq.content

        # RAG + GPT
        summary_text, rec1, rec2 = generate_gpt_answer(user_question)

        # DB 저장
        inq.gpt_summary = summary_text
        inq.gpt_recommendation_1 = rec1
        inq.gpt_recommendation_2 = rec2
        inq.gpt_used_answer_index = None
        inq.save()

        return JsonResponse({
            "status": "ok",
            "summary": summary_text,
            "recommendations": [rec1, rec2]
        })
    else:
        return JsonResponse({"status":"error","message":"Only GET allowed"}, status=405)
    




def inquiry_save_answer(request, inquiry_id):
    """
    POST /cs/inquiries/<inquiry_id>/save-answer/
    바디: answerContent=..., usedIndex=...
    """
    if request.method == "POST":
        inq = get_object_or_404(Inquiry, inquiry_id=inquiry_id)
        final_answer = request.POST.get('answerContent', '').strip()
        used_index = request.POST.get('usedIndex', '').strip()

        if not final_answer:
            return JsonResponse({"status":"error", "message":"No content provided"}, status=400)

        # DB 업데이트
        inq.answer_content = final_answer
        inq.answered = True

        # 채택된 GPT답변 인덱스 (예: 1 또는 2)
        if used_index in ['1','2']:
            inq.gpt_used_answer_index = int(used_index)
        else:
            inq.gpt_used_answer_index = None

        inq.save()

        return JsonResponse({"status":"ok", "message":"답변이 저장되었습니다.",
                             "answer_content": final_answer})
    else:
        return JsonResponse({"status":"error","message":"POST only"}, status=405)


def inquiry_center_list(request):
    """
    '플랫폼센터 문의' DB 조회 후, 템플릿 표시 (검색/필터/미답변 건수/구간 필터)
    CenterInquiry 모델 사용.
    """

    now = timezone.now()

    # 파라미터 추출
    search_query = request.GET.get('q', '')
    filter_status = request.GET.get('status', '')  # 'pending' or 'answered'
    time_range = request.GET.get('range', '')      # '24h', '24_72h', '72_30d'...
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    page_number = request.GET.get('page', '1')

    # 하나라도 필터/검색 파라미터가 있으면 collapse 열기
    open_collapse = bool(request.GET)

    # (1) 기본 쿼리: 최신순 (created_at_utc 내림차순)
    qs = CenterInquiry.objects.all().order_by('-created_at_utc')

    # (2) 구간 필터용 기준 시각
    cutoff_24h = now - timedelta(hours=24)
    cutoff_72h = now - timedelta(hours=72)
    cutoff_30d = now - timedelta(days=30)

    # (3) time_range 필터 (구간별 미답변)
    if time_range:
        # range 파라미터가 있으면 미답변만 필터
        qs = qs.filter(answered=False)
        if time_range == '24h':
            # 최근 24시간 이내
            qs = qs.filter(created_at_utc__gte=cutoff_24h)
        elif time_range == '24_72h':
            # 24시간 전 ~ 72시간 전 사이
            qs = qs.filter(
                created_at_utc__lt=cutoff_24h,
                created_at_utc__gte=cutoff_72h
            )
        elif time_range == '72_30d':
            # 72시간 전 ~ 30일 전 사이
            qs = qs.filter(
                created_at_utc__lt=cutoff_72h,
                created_at_utc__gte=cutoff_30d
            )

    # (4) 상태 필터 (pending/answered)
    if filter_status == 'pending':
        qs = qs.filter(answered=False)
    elif filter_status == 'answered':
        qs = qs.filter(answered=True)

    # (5) 검색어 필터 (inquiry_title, inquiry_content, author)
    if search_query:
        qs = qs.filter(
            Q(inquiry_title__icontains=search_query) |
            Q(inquiry_content__icontains=search_query) |
            Q(author__icontains=search_query)
        )

    # (6) 날짜 필터 (start_date, end_date) - created_at_utc의 날짜 기준
    if start_date_str:
        start_dt = parse_date(start_date_str)
        if start_dt:
            qs = qs.filter(created_at_utc__date__gte=start_dt)

    if end_date_str:
        end_dt = parse_date(end_date_str)
        if end_dt:
            qs = qs.filter(created_at_utc__date__lte=end_dt)

    # (7) 미답변 건수(24h / 24~72h / 72h~30일)
    # 각각 "해당 구간 내에 있고 answered=False"인 것의 개수
    count_24h = CenterInquiry.objects.filter(
        answered=False,
        created_at_utc__gte=cutoff_24h
    ).count()

    count_24_72h = CenterInquiry.objects.filter(
        answered=False,
        created_at_utc__lt=cutoff_24h,
        created_at_utc__gte=cutoff_72h
    ).count()

    count_72h_30d = CenterInquiry.objects.filter(
        answered=False,
        created_at_utc__lt=cutoff_72h,
        created_at_utc__gte=cutoff_30d
    ).count()

    # (8) 페이지네이션
    paginator = Paginator(qs, 50)  # 페이지당 50개
    page_obj = paginator.get_page(page_number)

    # (9) 각 페이지 항목들(inquiries) 구성
    inquiries = []
    for obj in page_obj:
        # 날짜 문자열
        date_str = ""
        if obj.created_at_utc:
            date_str = obj.created_at_utc.strftime('%Y-%m-%d %H:%M')

        # 상태
        status_str = "answered" if obj.answered else "pending"

        # 대표이미지
        representative_image = obj.representative_image or ""

        # 링크 prefix - store_name 또는 platform 중에 하나로 사용
        # 예: obj.store_name이 "쿠팡"/"NAVER" 등이라면 STORE_LINK_PREFIX에서 가져옴
        store_key = obj.store_name or obj.platform  # 우선 store_name 사용, 없으면 platform
        prefix = STORE_LINK_PREFIX.get(store_key, "")
        # product_link
        product_id_raw = obj.product_id or ""
        product_id_str = product_id_raw.replace("[", "").replace("]", "")
        product_link = f"{prefix}{product_id_str}" if prefix and product_id_str else ""

        # inquiries.append에 필요한 정보를 담아서 템플릿에 넘김
        inquiries.append({
            'id': obj.inquiry_id,  # <─ 템플릿에서 "문의번호"로 표시할 때 이 값을 씀
            'inquiry_id': obj.inquiry_id,
            'inquiry_title': obj.inquiry_title,
            'inquiry_content': obj.inquiry_content,
            'answer_content': obj.answer_content,  # <─ (2) 답변내용 추가
            'author': obj.author,
            'date': date_str,
            'status': status_str,
            'platform': obj.platform,
            'store_name': obj.store_name,
            'representative_image': representative_image,
            'product_link': product_link,
            'product_id_raw': product_id_raw,
            'product_id': product_id_str,  # 괄호 제거된 최종값
            # 필요 시 다른 필드도 추가
        })

    context = {
        'inquiries': inquiries,
        'page_obj': page_obj,
        'search_query': search_query,
        'filter_status': filter_status,
        'time_range': time_range,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'count_24h': count_24h,
        'count_24_72h': count_24_72h,
        'count_72h_30d': count_72h_30d,
        'open_collapse': open_collapse,
    }
    return render(request, 'cs_management/inquiry_center.html', context)

# def update_center_inquiries(request):
#     """
#     하나의 뷰에서 platform=naver/coupang/all 이면
#     네이버 + 쿠팡 "플랫폼센터 문의" API를 조회해서 DB에 저장.
    
#     GET 파라미터:
#       platform = 'naver' | 'coupang' | 'all'
#       answered = 'pending' | 'answered' (optional)
#         -> True or False or None
#     예) /cs/inquiries/center/update?platform=all&status=pending
#     """

#     logger.debug("[update_center_inquiries] --- START ---")

#     platform = request.GET.get('platform', '')   # "naver"/"coupang"/"all"
#     filter_status = request.GET.get('status', '')# 'pending'/'answered'
#     logger.debug(f"[update_center_inquiries] GET => platform={platform}, status={filter_status}")

#     # 1) answered 변환
#     answered = None
#     if filter_status == 'pending':
#         answered = False
#     elif filter_status == 'answered':
#         answered = True

#     logger.debug(f"[update_center_inquiries] => answered={answered}")

#     # (A) 네이버만
#     if platform == 'naver':
#         logger.debug("[update_center_inquiries] => NAVER 센터 계정 전체")
#         success, merged_data = fetch_naver_center_inquiries(answered=answered)
#         if success:
#             saved_objs = save_center_naver_inquiries_to_db(merged_data)
#             logger.info(f"[update_center_inquiries] NAVER Center saved={len(saved_objs)}")
#         else:
#             logger.error(f"[update_center_inquiries] NAVER Center 실패 => {merged_data}")

#     # (B) 쿠팡만
#     elif platform == 'coupang':
#         logger.debug("[update_center_inquiries] => 쿠팡 센터 계정 전체")
#         # partnerCounselingStatus => “NONE”(전체), “NO_ANSWER”, “ANSWER”, ...
#         # answered=True => "ANSWER", False => "NO_ANSWER", else => "NONE"
#         partner_status = "NONE"
#         if answered is True:
#             partner_status = "ANSWER"
#         elif answered is False:
#             partner_status = "NO_ANSWER"

#         success, merged_data = fetch_coupang_center_inquiries(partnerCounselingStatus=partner_status)
#         if success:
#             saved_objs = save_center_coupang_inquiries_to_db(merged_data)
#             logger.info(f"[update_center_inquiries] 쿠팡 Center saved={len(saved_objs)}")
#         else:
#             logger.error(f"[update_center_inquiries] 쿠팡 Center 실패 => {merged_data}")

#     # (C) “all” => 네이버+쿠팡
#     elif platform == 'all':
#         logger.debug("[update_center_inquiries] => 네이버+쿠팡 센터 모두 불러오기")

#         # 네이버
#         success_n, data_n = fetch_naver_center_inquiries(answered=answered)
#         if success_n:
#             saved_n = save_center_naver_inquiries_to_db(data_n)
#             logger.info(f"[update_center_inquiries] NAVER center => saved={len(saved_n)}")
#         else:
#             logger.error(f"[update_center_inquiries] NAVER center 실패 => {data_n}")

#         # 쿠팡
#         partner_status = "NONE"
#         if answered is True:
#             partner_status = "ANSWER"
#         elif answered is False:
#             partner_status = "NO_ANSWER"
#         success_c, data_c = fetch_coupang_center_inquiries(partnerCounselingStatus=partner_status)
#         if success_c:
#             saved_c = save_center_coupang_inquiries_to_db(data_c)
#             logger.info(f"[update_center_inquiries] 쿠팡 center => saved={len(saved_c)}")
#         else:
#             logger.error(f"[update_center_inquiries] 쿠팡 center 실패 => {data_c}")

#     else:
#         logger.warning(f"[update_center_inquiries] Unknown platform={platform}")

#     logger.debug("[update_center_inquiries] --- END ---")
#     return redirect('cs_management:inquiry_center_list')



def update_center_inquiries(request):
    """
    플랫폼센터 문의 API를 naver/coupang/all 한 번에 조회 후 DB 업데이트.
    - ?platform=naver
    - ?platform=coupang
    - ?platform=all
    """
    logger.debug("[update_center_inquiries] --- START ---")

    platform = request.GET.get('platform', 'all')
    logger.debug(f"[update_center_inquiries] platform={platform}")

    # 결과 임시 저장용
    naver_data = {}
    coupang_data = {}

    # (A) 네이버 센터 문의
    if platform in ['naver', 'all']:
        success_n, data_n = fetch_naver_center_inquiries()
        if success_n:
            naver_data = data_n  # { "contents":[...], "partial_errors":[...] }
            logger.debug("[update_center_inquiries] NAVER response => %s",
                         json.dumps(data_n, ensure_ascii=False, indent=2))
            # ★ DB 저장 로직
            saved_n = save_center_naver_inquiries_to_db(naver_data)
            logger.info(f"[update_center_inquiries] NAVER center => saved={len(saved_n)} inquiries.")
        else:
            logger.error(f"[update_center_inquiries] NAVER Center 실패 => {data_n}")

    # (B) 쿠팡 센터 문의
    if platform in ['coupang', 'all']:
        success_c, data_c = fetch_coupang_center_inquiries()
        if success_c:
            coupang_data = data_c  # { "contents":[...], "partial_errors":[...] }
            logger.debug("[update_center_inquiries] COUPANG response => %s",
                         json.dumps(data_c, ensure_ascii=False, indent=2))
            # ★ DB 저장 로직
            saved_c = save_center_coupang_inquiries_to_db(coupang_data)
            logger.info(f"[update_center_inquiries] 쿠팡 center => saved={len(saved_c)} inquiries.")
        else:
            logger.error(f"[update_center_inquiries] 쿠팡 Center 실패 => {data_c}")

    logger.debug("[update_center_inquiries] --- END ---")
    return redirect('cs_management:inquiry_center_list')


def delete_all_inquiries_center(request):
    """
    Inquiry 모델의 전체 데이터 삭제 뷰
    (주의: 보안/권한 처리 없이 간단히 구현)
    """
    CenterInquiry.objects.all().delete()
    logger.warning("[delete_all_inquiries_center] 모든 CenterInquiry 데이터가 삭제되었습니다.")
    return redirect('cs_management:inquiry_center_list')





@csrf_exempt
@require_POST
def answer_center_inquiry_unified(request):
    """
    고객센터 문의(CenterInquiry) 통합 답변 함수
    POST /cs/inquiries/answer-center-unified/
    요청 바디:
      - inquiry_id: CenterInquiry.inquiry_id
      - replyContent: 답변 내용
      (선택) usedIndex: GPT 답변 인덱스

    JS 예시 (버튼 클릭):
      const formData = new URLSearchParams();
      formData.append("inquiry_id", currentInquiryId);
      formData.append("replyContent", userReply);

      fetch("/cs/inquiries/answer-center-unified/", {
        method: "POST",
        headers:{
          "X-CSRFToken": "{{ csrf_token }}",
          "Content-Type":"application/x-www-form-urlencoded"
        },
        body: formData.toString()
      })
      .then(res => res.json())
      .then(data => { ... })
    """
    try:
        # 1) 파라미터 추출
        inquiry_id = request.POST.get('inquiry_id')
        reply_content = request.POST.get('replyContent', '').strip()
        used_index = request.POST.get('usedIndex', '').strip()

        logger.debug(
            f"[answer_center_inquiry_unified] inquiry_id={inquiry_id}, "
            f"reply_content={reply_content}, used_index={used_index}"
        )
        if not inquiry_id or not reply_content:
            return JsonResponse({
                'status':'error',
                'message':'Missing inquiry_id or replyContent'
            }, status=400)

        # 2) DB에서 CenterInquiry 찾기
        inq = get_object_or_404(CenterInquiry, inquiry_id=inquiry_id)

        # 3) 플랫폼별 답변 API 호출
        platform = (inq.platform or "").upper()
        store_name = inq.store_name or ""
        logger.debug(f"[answer_center_inquiry_unified] platform={platform}, store_name={store_name}")

        if platform == "NAVER":
            # (A) 네이버 로직
            # store_name 에 맞는 account_info 찾기
            account_info = next(
                (acc for acc in NAVER_ACCOUNTS if store_name in acc['names']),
                None
            )
            logger.debug(f"[answer_center_inquiry_unified] NAVER account_info={account_info}")

            if not account_info:
                msg = f"No Naver account for store={store_name}"
                logger.error(msg)
                return JsonResponse({'status':'error','message':msg}, status=404)

            # 네이버 '고객센터 문의'용 API => put_naver_qna_center_answer(...)
            success, result = put_naver_qna_center_answer(
                account_info=account_info,
                inquiry_no=inq.inquiry_id,
                answer_comment=reply_content
            )
            if not success:
                logger.error(f"[answer_center_inquiry_unified] NAVER API 실패: {result}")
                return JsonResponse({'status':'error','message':f'네이버 API 실패: {result}'}, status=400)

        elif platform == "COUPANG":
            # (B) 쿠팡 로직 (예시)
            # account_info = next(
            #     (acc for acc in COUPANG_ACCOUNTS if store_name in acc['names']),
            #     None
            # )
            # if not account_info:
            #     msg = f"No Coupang account for store={store_name}"
            #     logger.error(msg)
            #     return JsonResponse({'status':'error','message':msg}, status=404)

            # success, result = put_coupang_center_inquiry_answer(
            #     account_info=account_info,
            #     inquiry_id=inq.inquiry_id,
            #     answer_comment=reply_content
            # )
            # if not success:
            #     logger.error(f"[answer_center_inquiry_unified] 쿠팡 API 실패: {result}")
            #     return JsonResponse({'status':'error','message':f'쿠팡 API 실패: {result}'}, status=400)
            pass

        else:
            # (C) 그 외 플랫폼, 혹은 아무 것도 안 함
            logger.debug(f"[answer_center_inquiry_unified] Unknown or no platform for inquiry_id={inquiry_id}")

        # 4) 로컬 DB 업데이트
        inq.answer_content = reply_content
        inq.answered = True
        inq.answered_at = timezone.now()

        # GPT 답변 인덱스 (1 or 2)
        if used_index in ['1','2']:
            inq.gpt_used_answer_index = int(used_index)

        inq.save()

        # 5) 성공 응답
        return JsonResponse({
            'status':'ok',
            'message':'고객센터 문의 답변 등록 성공',
            'answer_content': inq.answer_content
        })

    except Exception as e:
        logger.exception("[answer_center_inquiry_unified] error")
        return JsonResponse({'status':'error','message':str(e)}, status=500)