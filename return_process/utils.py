# return_process/utils.py

from .models import ReturnItem
from datetime import datetime

def save_return_items(data, platform):
    for item in data:
        logger.info(f"저장하는 아이템: {item}")
        ReturnItem.objects.update_or_create(
            order_id=item['orderId'],  # 주문번호
            defaults={
                'product_name': item.get('productName', ''),
                'customer_name': item.get('customerName', ''),
                'status': item.get('status', ''),
                'requested_date': datetime.strptime(item['requestedDate'], '%Y-%m-%dT%H:%M:%S'),
                'platform': platform,
                # 추가로 저장하고 싶은 필드를 여기에 추가
            }
        )
