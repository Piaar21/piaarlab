# webhook/views.py
import json
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

# utils.py에서 필요한 함수만 임포트
from .utils import (
    get_product_options,
    get_stock_by_option_codes,
    join_data
)

@csrf_exempt
def webhook(request):
    """
    카카오톡 챗봇(또는 다른 플랫폼)에서 들어온 Webhook 요청을 처리하는 Django View.
    ChatGPT 관련 코드는 제외하고, 오직 /ㅈㄱ 로직만 구현.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'], "Only POST method is allowed.")

    try:
        data = json.loads(request.body)  # 들어온 JSON 데이터를 파싱
        user_message = data.get('userRequest', {}).get('utterance', '').strip()

        # /ㅈㄱ로 시작하면 재고 조회
        if user_message.startswith('/ㅈㄱ'):
            product_name = user_message[len('/ㅈㄱ'):].strip()

            if product_name:
                # 1) 상품 옵션 조회
                product_options = get_product_options(product_name)
                if product_options:
                    # 2) 옵션 코드 목록 추출
                    option_codes = [
                        item['productOptionCode'].strip().upper()
                        for item in product_options if 'productOptionCode' in item
                    ]
                    if not option_codes:
                        response_text = f"'{product_name}'에 해당하는 옵션 코드를 찾을 수 없습니다."
                    else:
                        # 3) 재고 조회
                        stock_data = get_stock_by_option_codes(option_codes)
                        if stock_data:
                            # 4) 옵션+재고 데이터를 조합
                            joined = join_data(product_options, stock_data)
                            if joined:
                                # 옵션+재고 정보 문구 생성
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

        # /ㅈㄱ 외 다른 명령어인 경우
        else:
            response_text = "알 수 없는 명령입니다. '/ㅈㄱ 상품명' 형태로 입력해주세요."

        # 카카오톡 챗봇에 맞는 JSON 응답 포맷
        kakao_response = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": response_text
                        }
                    }
                ]
            }
        }
        return JsonResponse(kakao_response)

    except Exception as e:
        print(f"[webhook] 오류 발생: {e}")
        return JsonResponse({"error": "서버 오류가 발생했습니다."}, status=500)
