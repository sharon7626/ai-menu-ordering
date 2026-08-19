import os
import tempfile
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from backend.database import initialize_database, save_group_menu
from backend.group_orders import hash_secret_token
from backend.main import app


MENU = {
    "restaurant": {"name": "表格測試店"},
    "categories": [
        {
            "id": "drinks",
            "name": "飲料",
            "items": [
                {
                    "id": "black-tea",
                    "name": "紅茶（L）",
                    "description": "",
                    "price": 35,
                    "available": True,
                }
            ],
        }
    ],
}


class GroupExcelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "excel.db"
        initialize_database(database_path)
        self.management_token = "excel-management-token"
        save_group_menu(
            public_code="XLS234",
            management_token_hash=hash_secret_token(self.management_token),
            menu=MENU,
            created_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            database_path=database_path,
        )
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                for customer, note, quantity, contact_value in (
                    ("小美", "半糖少冰", 2, "0912345678"),
                    ("小華", "無糖去冰", 1, "0987654321"),
                ):
                    response = client.post(
                        "/api/groups/XLS234/orders",
                        json={
                            "customer_name": customer,
                            "contact_method": "phone",
                            "contact_value": contact_value,
                            "items": [{"item_id": "black-tea", "quantity": quantity, "note": note}],
                        },
                    )
                    self.assertEqual(response.status_code, 201)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _download(self, token: str):
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                return client.get(
                    "/api/groups/XLS234/management.xlsx",
                    headers={"Authorization": f"Bearer {token}"},
                )

    def test_management_can_download_valid_xlsx_with_three_sheets(self) -> None:
        response = self._download(self.management_token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("group-XLS234-orders.xlsx", response.headers["content-disposition"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(int(response.headers["content-length"]), len(response.content))
        self.assertEqual(response.headers["x-order-count"], "2")
        self.assertEqual(response.headers["x-grand-total"], "105")
        self.assertGreater(len(response.content), 1000)

        with ZipFile(BytesIO(response.content)) as workbook:
            self.assertEqual(workbook.testzip(), None)
            self.assertIn("xl/worksheets/sheet1.xml", workbook.namelist())
            self.assertIn("xl/worksheets/sheet2.xml", workbook.namelist())
            self.assertIn("xl/worksheets/sheet3.xml", workbook.namelist())
            workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
            summary_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
            purchasers_xml = workbook.read("xl/worksheets/sheet2.xml").decode("utf-8")
            details_xml = workbook.read("xl/worksheets/sheet3.xml").decode("utf-8")

        self.assertIn("餐點彙整", workbook_xml)
        self.assertIn("訂購者合計", workbook_xml)
        self.assertIn("個人明細", workbook_xml)
        self.assertIn("2 張", summary_xml)
        self.assertIn("NT$ 105", summary_xml)
        self.assertIn("紅茶（L）", summary_xml)
        self.assertIn("半糖少冰", summary_xml)
        self.assertIn("無糖去冰", summary_xml)
        self.assertIn("餐點總數量", purchasers_xml)
        self.assertIn("身分辨識", purchasers_xml)
        self.assertIn("手機：0912345678", purchasers_xml)
        self.assertIn("合計金額", purchasers_xml)
        self.assertIn("小美", purchasers_xml)
        self.assertIn("小華", purchasers_xml)
        self.assertIn(">2</", purchasers_xml)
        self.assertIn(">70</", purchasers_xml)
        self.assertIn(">35</", purchasers_xml)
        self.assertIn("小美", details_xml)
        self.assertIn("身分辨識", details_xml)
        self.assertIn("小華", details_xml)
        self.assertNotIn(self.management_token, response.content.decode("latin-1"))

        summary_root = ET.fromstring(summary_xml)
        child_names = [element.tag.rsplit("}", 1)[-1] for element in summary_root]
        self.assertLess(child_names.index("autoFilter"), child_names.index("mergeCells"))

    def test_wrong_token_cannot_download_xlsx(self) -> None:
        response = self._download("wrong-token")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
