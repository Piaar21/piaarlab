from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from .models import DelayedShipment


def _build_excel_file(rows, name="delayed-orders.xlsx"):
    workbook = Workbook()
    worksheet = workbook.active

    for row in rows:
        worksheet.append(row)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return SimpleUploadedFile(
        name,
        output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class UploadDelayedOrdersTests(TestCase):
    def test_upload_excel_accepts_numeric_cells(self):
        upload_file = _build_excel_file(
            [
                [
                    "option_code",
                    "customer_name",
                    "customer_contact",
                    "order_product_name",
                    "order_option_name",
                    "quantity",
                    "seller_product_name",
                    "seller_option_name",
                    "order_number_1",
                    "order_number_2",
                    "store_name",
                ],
                [
                    "OPT-001",
                    "홍길동",
                    "01012345678",
                    "주문상품",
                    "옵션A",
                    2,
                    "셀러상품",
                    "셀러옵션",
                    123456789,
                    987654321,
                    "테스트스토어",
                ],
            ]
        )

        response = self.client.post(
            reverse("upload_delayed_orders"),
            {"upload_excel": "1", "file": upload_file},
        )

        self.assertEqual(response.status_code, 302)

        temp_orders = self.client.session["delayed_orders_temp"]
        self.assertEqual(len(temp_orders), 1)
        self.assertEqual(temp_orders[0]["quantity"], "2")
        self.assertEqual(temp_orders[0]["order_number_1"], "123456789")
        self.assertEqual(temp_orders[0]["order_number_2"], "987654321")

    @patch("delayed_management.views.update_restock_from_sheet")
    @patch("delayed_management.views.store_mapping_for_ids")
    @patch("delayed_management.views.extract_options_for_ids")
    def test_finalize_handles_legacy_numeric_session_values(
        self,
        extract_options_for_ids_mock,
        store_mapping_for_ids_mock,
        update_restock_from_sheet_mock,
    ):
        session = self.client.session
        session["delayed_orders_temp"] = [
            {
                "option_code": "OPT-002",
                "customer_name": "김철수",
                "customer_contact": 1012345678,
                "order_product_name": "주문상품",
                "order_option_name": "옵션B",
                "quantity": 3,
                "seller_product_name": "셀러상품",
                "seller_option_name": "셀러옵션",
                "order_number_1": 555000111,
                "order_number_2": 999000111,
                "store_name": "테스트스토어",
            }
        ]
        session.save()

        response = self.client.post(
            reverse("upload_delayed_orders"),
            {"finalize": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(DelayedShipment.objects.count(), 1)

        shipment = DelayedShipment.objects.get()
        self.assertEqual(shipment.customer_contact, "1012345678")
        self.assertEqual(shipment.quantity, "3")
        self.assertEqual(shipment.order_number_1, "555000111")
        self.assertEqual(shipment.order_number_2, "999000111")

        extract_options_for_ids_mock.assert_called_once()
        store_mapping_for_ids_mock.assert_called_once()
        update_restock_from_sheet_mock.assert_called_once()
