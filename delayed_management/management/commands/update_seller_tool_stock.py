# delayed_management/management/commands/update_seller_tool_stock.py

from django.core.management.base import BaseCommand
from django.test.client import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.auth.models import AnonymousUser

from delayed_management.views import update_seller_tool_and_increase_stock_view

class Command(BaseCommand):
    help = "셀러툴 재고 업데이트 후 플랫폼 재고 추가"

    def _make_request(self):
        # RequestFactory 로 빈 request 생성
        factory = RequestFactory()
        request = factory.get('/')

        # 세션 미들웨어 적용 (messages 에 필요)
        SessionMiddleware(get_response=lambda r: None).process_request(request)
        request.session.save()

        # messages 미들웨어 적용
        MessageMiddleware(get_response=lambda r: None).process_request(request)

        # 로그인 필요 없는 뷰라면 AnonymousUser, 아니면 실제 관리자 계정 로드
        request.user = AnonymousUser()
        return request

    def handle(self, *args, **options):
        self.stdout.write("=== [관리커맨드] 셀러툴 재고 업데이트 작업 시작 ===")
        request = self._make_request()
        # 이제 messages.* 와 redirect() 모두 안전
        update_seller_tool_and_increase_stock_view(request)
        self.stdout.write("=== [관리커맨드] 작업 완료 ===")
