# cs_management/views.py
from django.shortcuts import render, redirect, get_object_or_404
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import logging
from decouple import config
from .api_clients import send_message_to_talk
import requests
from .models import ChatRoom, ChatMessage
import os
from django.conf import settings
import uuid
from django.utils import timezone


def chat_inquiry(request):
    """
    왼쪽에 ChatRoom 목록을 보여주고,
    중앙에는 간단한 안내 or 샘플 메시지를 표시
    """
    rooms = ChatRoom.objects.order_by('-created_at')  # 최신 순
    context = {
        'rooms': rooms
    }
    return render(request, 'cs_management/chat_inquiry.html', context)

def chat_inquiry_detail(request, user_id):
    """
    특정 user_id의 대화 상세 보기
    - 왼쪽에는 동일하게 ChatRoom 목록
    - 중앙에는 해당 user_id의 실제 메시지 목록
    """
    # 해당 user_id 방 가져오기
    room = get_object_or_404(ChatRoom, user_id=user_id)
    display_name = room.nickname if room.nickname else room.user_id
    room.messages.filter(direction='inbound', seen=False).update(seen=True)
    messages = room.messages.order_by('created_at')[:50]  # 최근 50개

    # 좌측 방 목록도 동일하게 보여주기 위해
    rooms = ChatRoom.objects.order_by('-created_at')

    context = {
        'rooms': rooms,
        'room': room,
        'messages': messages,
        'display_name': display_name,
    }
    return render(request, 'cs_management/chat_inquiry_detail.html', {'room': room, 'display_name': display_name})

logger = logging.getLogger(__name__)

def get_messages_json(request, user_id):
    """
    Ajax로 메시지 목록 요청 시, JSON으로 반환
    """
    room = get_object_or_404(ChatRoom, user_id=user_id)
    msgs = room.messages.order_by('created_at')

    data = []
    for m in msgs:
        data.append({
            'text': m.text,
            'direction': m.direction,   # 'inbound' or 'outbound'
            'created_at': m.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'image_url': m.image_url or ""  # <-- 추가: 이미지 URL
        })
    return JsonResponse({'messages': data}, safe=False)


@csrf_exempt
def naver_talk_callback(request):
    """
    네이버 톡톡 콜백(Webhook)
    1) event='send' 시: 메시지 DB 저장, 닉네임 없는 경우 profile API 자동 요청
    2) event='profile' 시: 닉네임/주소/휴대폰 등 DB 저장
    """
    if request.method != 'POST':
        return HttpResponse("Only POST allowed", status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event = body.get('event', '')
    user_id = body.get('user', '')
    options = body.get('options', {})

    # 메시지 텍스트
    text_content = body.get('textContent', {}).get('text', '')

    # 이미지(옵션)
    image_content = body.get('imageContent')
    image_url = ""
    if image_content:
        image_url = image_content.get('imageUrl', '')  # 네이버 톡톡 임시 경로

    if event == 'send':
        # 1) 메시지(DB 저장)
        if user_id:
            room, created = ChatRoom.objects.get_or_create(user_id=user_id)

            ChatMessage.objects.create(
                room=room,
                direction='inbound',
                text=text_content or "",
                image_url=image_url or "",
                seen=False
            )

            # 2) 닉네임이 없는 경우 자동 닉네임 요청
            if not getattr(room, 'nickname', None):
                logger.info(f"[AUTO-PROFILE] user_id={user_id} -> nickname not found, requesting profile.")
                request_profile_api(user_id, field="nickname")

        return HttpResponse(status=200)

    elif event == 'profile':
        # 3) 프로필 응답
        result = options.get('result')  # SUCCESS / DISAGREE / CANCEL
        nickname = options.get('nickname')
        cellphone = options.get('cellphone')
        address = options.get('address', {})

        if result == 'SUCCESS':
            room, created = ChatRoom.objects.get_or_create(user_id=user_id)
            if nickname:
                room.nickname = nickname
                room.save()
            # cellphone, address도 필요한 경우 room에 저장
            logger.info(f"[PROFILE] user_id={user_id}, nickname={nickname}, phone={cellphone}, address={address}")

        elif result == 'CANCEL':
            logger.info(f"[PROFILE] user_id={user_id} -> 사용자 거부 or 미등록")
        else:
            logger.info(f"[PROFILE] user_id={user_id} -> result={result}")

        return HttpResponse(status=200)

    # open, leave 등 무시
    return HttpResponse(status=200)


def request_profile_api(user_id, field="nickname"):
    """
    네이버 톡톡 'profile' 이벤트를 전송해서 
    사용자 닉네임(or address, cellphone) 요청
    """
    talk_send_auth = config('TALK_SEND_API_KEY', default='')
    url = "https://gw.talk.naver.com/chatbot/v1/event"

    payload = {
        "event": "profile",
        "options": {
            "field": field,
            "agreements": ["cellphone", "address"]  # 동의 절차에 함께 요청할 수도 있음
        },
        "user": user_id
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": talk_send_auth
    }

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 200:
        logger.info(f"[request_profile_api] Profile request sent: field={field}, user_id={user_id}")
    else:
        logger.warning(f"[request_profile_api] Failed: status={response.status_code}, text={response.text}")
    return response.status_code


def send_image_to_talk(user_id, image_url, width=600, height=400):
    """
    네이버 톡톡(보내기 API)로 이미지 메시지 전송
    """
    url = "https://gw.talk.naver.com/chatbot/v1/event"
    talk_send_auth = config('NAVER_TALK_SEND_API_KEY', default='')

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Authorization": talk_send_auth,
    }
    payload = {
        "event": "send",
        "user": user_id,
        "imageContent": {
            "imageUrl": image_url,
            "width": width,
            "height": height
        }
    }

    response = requests.post(url, json=payload, headers=headers)
    return response


@csrf_exempt
def send_push_message_view(request):
    """
    예시: /cs/chat/send-push/ 경로로 POST 요청 시,
         user_id와 message를 받아 톡톡 '보내기 API'로 메시지 푸시
    """
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        message_text = request.POST.get('message')

        if not user_id or not message_text:
            return JsonResponse({"error": "user_id and message are required"}, status=400)

        # 보내기 API 호출
        resp = send_message_to_talk(user_id, message_text)
        try:
            resp_data = resp.json()
        except:
            resp_data = {"success": False, "resultCode": "JSON-ERROR"}

        # 예시 응답
        return JsonResponse({
            "status_code": resp.status_code,
            "response": resp_data
        })

    else:
        return HttpResponse("Only POST allowed", status=405)
    

def send_message_to_talk(user_id, message_text):
    """
    네이버 톡톡 보내기 API (우리 -> 사용자)
    """
    url = "https://gw.talk.naver.com/chatbot/v1/event"
    talk_send_auth = config('NAVER_TALK_SEND_API_KEY', default='')

    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Authorization": talk_send_auth,
    }
    payload = {
        "event": "send",
        "user": user_id,
        "textContent": {
            "text": message_text
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    return resp

def upload_image(image_file):
    # 확장자 추출
    ext = os.path.splitext(image_file.name)[1]  # ex) '.png'
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(settings.MEDIA_ROOT, filename)

    # 폴더가 없으면 생성
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

    with open(filepath, 'wb') as f:
        for chunk in image_file.chunks():
            f.write(chunk)

    # 최종 브라우저에서 접근할 URL (MEDIA_URL + 파일명)
    return f"{settings.MEDIA_URL}{filename}"



@csrf_exempt
def chat_send_message(request):
    """
    사용자(상담사)가 입력한 메시지를 AJAX로 받아, 
    특정 user_id에게 네이버 톡톡 메시지를 보낸 뒤 JSON을 반환.
    - 텍스트 + (선택) 이미지 파일도 가능
    - 성공 시: { "success": true, "resultCode": "00" }
    - 실패 시: { "success": false, "error": "..."}
    """
    if request.method != 'POST':
        return JsonResponse({"success": False, "error": "Only POST allowed"}, status=405)

    user_id = request.POST.get('user_id', '').strip()
    message_text = request.POST.get('message_text', '').strip()
    image_file = request.FILES.get('image_file', None)  # <input type="file" name="image_file">

    # 텍스트+이미지 모두 없음 -> 에러
    if not user_id or (not message_text and not image_file):
        return JsonResponse({"success": False, "error": "user_id 또는 (message_text, image_file) 모두 비었습니다."},
                            status=400)

    # ChatRoom 확인
    try:
        room = ChatRoom.objects.get(user_id=user_id)
    except ChatRoom.DoesNotExist:
        return JsonResponse({"success": False, "error": f"ChatRoom({user_id}) 없음."}, status=404)

    # 이미지 업로드(가상의 upload_image 함수) -> image_url
    image_url = ""
    if image_file:
        image_url = upload_image(image_file)  # TODO: 실제 구현 필요

    # [수정] outbound 메시지: DB에 딱 1회만 생성
    msg = ChatMessage.objects.create(
        room=room,
        text=message_text or "",
        image_url=image_url,
        direction='outbound'
    )

    # send to 네이버 톡톡
    if image_url and not message_text:
        # 이미지만 전송
        response = send_image_to_talk(user_id, image_url)
    elif image_url and message_text:
        # 이미지 + 텍스트 (단순히 2번 보낼 수도, compositeContent 사용 가능)
        resp_img = send_image_to_talk(user_id, image_url)
        resp_txt = send_message_to_talk(user_id, message_text)
        response = resp_txt  # 여기서는 resp_txt 결과 기준
    else:
        # 텍스트만
        response = send_message_to_talk(user_id, message_text)

    if response is None:
        return JsonResponse({"success": False, "error": "API 요청 실패(None)"}, status=500)

    try:
        resp_data = response.json()  # { "success": true, "resultCode": "00" } 등
    except:
        return JsonResponse({"success": False, "error": "API 응답 파싱 실패"}, status=500)

    if resp_data.get('success') is True:
        return JsonResponse({"success": True, "resultCode": resp_data.get('resultCode', '00')}, status=200)
    else:
        return JsonResponse({"success": False, "error": resp_data}, status=500)




def format_relative_time(dt):
    local_dt = timezone.localtime(dt)  # dt를 localtime으로 변환
    # Django의 tz-aware 현재 시각
    now = timezone.now()

    # 만약 dt가 naive라면, make_aware로 tz 부여(임시방편):
    # from django.utils import timezone
    # if dt.tzinfo is None:
    #     dt = timezone.make_aware(dt, timezone.get_current_timezone())

    diff = now - dt
    secs = diff.total_seconds()
    mins = int(secs // 60)
    hours = int(secs // 3600)
    days = diff.days

    if secs < 60:
        return "방금"
    elif mins < 60:
        return f"{mins}분 전"
    elif hours < 24:
        return f"{hours}시간 전"
    elif days == 1:
        return "어제"
    else:
        return dt.strftime("%m월 %d일")

@csrf_exempt
def get_rooms_json(request):
    """
    AJAX로 ChatRoom 목록 + 마지막 메시지 + 안 읽은 메시지 개수 + 상대 시각 반환
    """
    rooms = ChatRoom.objects.order_by('-created_at')
    data = []

    for room in rooms:
        last_msg = room.messages.order_by('-created_at').first()
        if last_msg:
            if last_msg.image_url:
                last_text = "사진"  # 이미지면 "사진"
            else:
                # 텍스트 잘라서 표시 (예: 최대 30자)
                last_text = (last_msg.text[:30] + "...") if len(last_msg.text) > 30 else last_msg.text
        else:
            last_text = ""

        # 안 읽은 메시지: inbound+seen=False (가정)
        unread_count = room.messages.filter(direction='inbound', seen=False).count()

        # 상대 시각
        relative_time = format_relative_time(room.created_at)

        data.append({
            "user_id": room.user_id,
            "relative_time": relative_time,     # "방금", "1분 전" 등
            "last_text": last_text,            # 텍스트 or "사진"
            "unread_count": unread_count,
            "nickname": room.nickname,  # ← 닉네임도 포함
        })

    return JsonResponse({"rooms": data}, safe=False)


@csrf_exempt
def naver_talk_echo(request):
    """
    네이버 톡톡에서 보내는 각종 이벤트를 판별하고
    적절한 메시지로 회신(Echo)하는 예제
    """
    if request.method != 'POST':
        return HttpResponse("Only POST is allowed", status=405)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    # 디버그 용: request body 출력
    print("[NaverTalk] Received body:", body)

    # 기본 응답 구조
    # Node.js 예제에서
    #   let response = {
    #       event: 'send',
    #       textContent: { text: '' }
    #   };
    response = {
        "event": "send",  # send message (기본)
        "textContent": {
            "text": ""
        }
    }

    event_type = body.get("event", "")
    text_content = body.get("textContent", {})
    options = body.get("options", {})

    # 이벤트별 분기 처리
    if event_type == "send":
        # 사용자가 보낸 메시지에 대해 Echo 응답
        user_text = text_content.get("text", "")
        if user_text:
            response["textContent"]["text"] = f"echo: {user_text}"
            return JsonResponse(response)
        else:
            # textContent가 없는 경우 무반응
            return HttpResponse(status=200)

    elif event_type == "open":
        # 채팅창 오픈 이벤트
        inflow = options.get("inflow", "none")

        if inflow == "list":
            response["textContent"]["text"] = "목록에서 눌러서 방문하셨네요."
            return JsonResponse(response)
        elif inflow == "button":
            response["textContent"]["text"] = "버튼을 눌러서 방문하셨네요."
            return JsonResponse(response)
        elif inflow == "none":
            response["textContent"]["text"] = "방문을 환영합니다."
            return JsonResponse(response)
        else:
            # 그 외 inflow 값은 무반응
            return HttpResponse(status=200)

    elif event_type == "friend":
        # 친구 추가/철회 이벤트
        friend_set = options.get("set", "")
        if friend_set == "on":
            response["textContent"]["text"] = "친구가 되어 주셔서 감사합니다."
            return JsonResponse(response)
        elif friend_set == "off":
            response["textContent"]["text"] = "다음 번에 꼭 친구 추가 부탁드려요."
            return JsonResponse(response)
        else:
            return HttpResponse(status=200)

    else:
        # 그 외 이벤트는 무반응
        return HttpResponse(status=200)
    

def product_inquiry(request):
    """
    상품 문의 페이지
    """
    # 필요한 로직(예: API 호출, DB 조회 등)
    context = {
        # 'some_data': ...
    }
    return render(request, 'cs_management/product_inquiry.html', context)


def customer_center_inquiry(request):
    """
    고객센터 문의 페이지
    """
    # 필요한 로직(예: API 호출, DB 조회 등)
    context = {
        # 'some_data': ...
    }
    return render(request, 'cs_management/customer_center_inquiry.html', context)


