from django.core.management.base import BaseCommand
from django.utils import timezone
from delayed_management.views import update_seller_tool_and_increase_stock_view

class Command(BaseCommand):
    help = "셀러툴 재고 업데이트 후 플랫폼 재고 추가"

    def handle(self, *args, **options):
        # 원하는 함수 호출
        # (주의: 일반적으로는 뷰 함수를 직접 import해서 쓰지 않고,
        #  로직을 별도 service 함수 등에 분리해 두는 것이 좋습니다.)
        print("=== [관리커맨드] 셀러툴 재고 업데이트 작업 시작 ===")

        # 뷰 함수가 request를 필요로 한다면 바로 사용 어려울 수 있음.
        # 보통 request 없이도 동작 가능하도록 로직을 별도 모듈로 분리하는 편.
        # 일단 예시로 가정
        update_seller_tool_and_increase_stock_view(None)

        print("=== [관리커맨드] 작업 완료 ===")
