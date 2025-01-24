# cs_management/api_clients.py

import requests
import logging
from decouple import config

logger = logging.getLogger(__name__)

def send_message_to_talk(user_id, message_text):
    talk_send_auth = config('NAVER_TALK_SEND_API_KEY')
    print("[DEBUG] talk_send_auth =", talk_send_auth)  # 추가def send_message_to_talk(user_id, message_text):
    """
    네이버 톡톡(보내기 API)을 사용해 특정 사용자(user_id)에게 메시지를 전송하는 함수.
    """
    # 1) 보내기 API URL
    url = "https://gw.talk.naver.com/chatbot/v1/event"


    if not talk_send_auth:
        logger.error("NAVER_TALK_SEND_API_KEY가 설정되지 않음!")
        return None

    # 만약 Bearer가 필요하다면 아래처럼 변경:
    # headers["Authorization"] = f"Bearer {talk_send_auth}"
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

    logger.info(f"[send_message_to_talk] user_id={user_id}, text='{message_text}'")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        logger.debug(f"[send_message_to_talk] status={response.status_code}, body={response.text}")

        # 3) HTPP 응답코드 2xx 외엔 에러 처리
        response.raise_for_status()

        return response
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"[send_message_to_talk] HTTP error occurred: {http_err}")
        return None
    except requests.exceptions.RequestException as req_err:
        logger.error(f"[send_message_to_talk] RequestException: {req_err}")
        return None