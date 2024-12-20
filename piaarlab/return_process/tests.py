# return_process/tests.py
from django.test import TestCase
from .models import ReturnItem

class ReturnItemTestCase(TestCase):
    def setUp(self):
        ReturnItem.objects.create(order_id='12345', product_name='테스트 상품')

    def test_return_item_creation(self):
        item = ReturnItem.objects.get(order_id='12345')
        self.assertEqual(item.product_name, '테스트 상품')
