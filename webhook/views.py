import re
import json
from django.db.models import Q
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from .utils import (
    get_product_options,
    get_stock_by_option_codes,
    join_data
)
from delayed_management.models import DelayedShipment

@csrf_exempt
def webhook(request):
    """
    카카오톡 챗봇에서 들어온 Webhook 요청을 처리.
    - /ㅈㄱ: 재고 조회 (SellerTool API)
    - /ㅇㄱ: 재입고 예상날짜 안내 (DelayedShipment)
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'], "Only POST method is allowed.")

    try:
        data = json.loads(request.body)
        user_message = data.get('userRequest', {}).get('utterance', '').strip()
        print(f"[DEBUG] user_message = {user_message}")

        # ----------------------------------------------------------
        # 1) /ㅈㄱ 재고 조회
        # ----------------------------------------------------------
        if user_message.startswith('/ㅈㄱ'):
            product_name = user_message[len('/ㅈㄱ'):].strip()
            # 공백 제거 버전도 준비
            product_name_no_space = re.sub(r'\s+', '', product_name)
            print(f"[DEBUG] '/ㅈㄱ' 명령어. product_name={product_name}, no_space={product_name_no_space}")

            if product_name:
                # 1) 먼저 공백 포함 버전으로 상품 옵션 조회
                product_options = get_product_options(product_name)

                # 2) 만약 결과가 없으면(또는 None) → 공백 제거 버전으로 재시도
                if not product_options:
                    product_options = get_product_options(product_name_no_space)

                if product_options:
                    # 옵션 코드 목록 추출
                    option_codes = [
                        item['productOptionCode'].strip().upper()
                        for item in product_options if 'productOptionCode' in item
                    ]
                    if not option_codes:
                        response_text = f"'{product_name}'에 해당하는 옵션 코드를 찾을 수 없습니다."
                    else:
                        # 재고 조회
                        stock_data = get_stock_by_option_codes(option_codes)
                        if stock_data:
                            # 옵션+재고 조인
                            joined = join_data(product_options, stock_data)
                            if joined:
                                lines = [
                                    f"옵션: {item.get('productOptionName')} / 재고: {item.get('재고 수량')}"
                                    for item in joined
                                ]
                                response_text = "\n".join(lines)
                            else:
                                response_text = "옵션과 재고 정보를 조합할 수 없습니다."
                        else:
                            response_text = "재고 정보를 가져올 수 없습니다."
                else:
                    response_text = f"'{product_name}' 상품의 옵션 정보를 가져올 수 없습니다."
            else:
                response_text = "사용 예: '/ㅈㄱ 상품명' 형태로 입력해주세요."

        # ----------------------------------------------------------
        # 2) /ㅇㄱ 재입고 날짜 안내
        # ----------------------------------------------------------
        elif user_message.startswith('/ㅇㄱ'):
            product_name = user_message[len('/ㅇㄱ'):].strip()
            # 공백 제거 버전
            product_name_no_space = re.sub(r'\s+', '', product_name)
            print(f"[DEBUG] '/ㅇㄱ' 명령어. product_name={product_name}, no_space={product_name_no_space}")

            if product_name:
                # OR 조건: seller_product_name / order_product_name 에서
                # 공백 포함 검색 + 공백 제거 검색  (icontains)
                shipments = DelayedShipment.objects.filter(
                    Q(seller_product_name__icontains=product_name)
                    | Q(seller_product_name__icontains=product_name_no_space)
                    | Q(order_product_name__icontains=product_name)
                    | Q(order_product_name__icontains=product_name_no_space)
                )

                if shipments.exists():
                    lines = []
                    for s in shipments:
                        if s.expected_restock_date:
                            lines.append(
                                f"옵션코드: {s.option_code}, "
                                f"옵션명: {s.order_option_name or s.seller_option_name}, "
                                f"재입고 예상날짜: {s.expected_restock_date.strftime('%Y-%m-%d')}"
                            )
                        else:
                            lines.append(
                                f"옵션코드: {s.option_code}, "
                                f"옵션명: {s.order_option_name or s.seller_option_name}, "
                                f"재입고 예상날짜: (미정)"
                            )
                    response_text = "\n".join(lines)
                else:
                    response_text = "입고 예정이 없는 상품입니다."
            else:
                response_text = "사용 예: '/ㅇㄱ 상품명' 형태로 입력해주세요."

        # ----------------------------------------------------------
        # 3) 그 외 명령어
        # ----------------------------------------------------------
        else:
            print("[DEBUG] /ㅈㄱ, /ㅇㄱ 명령어가 아님.")
            response_text = (
                "알 수 없는 명령입니다.\n"
                "• '/ㅈㄱ 상품명' = 재고 조회\n"
                "• '/ㅇㄱ 상품명' = 재입고 예상날짜 안내"
            )

        # 카카오톡 응답 포맷
        kakao_response = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {"text": response_text}
                    }
                ]
            }
        }
        return JsonResponse(kakao_response)

    except Exception as e:
        print(f"[webhook] 오류 발생: {e}")
        return JsonResponse({"error": "서버 오류가 발생했습니다."}, status=500)
