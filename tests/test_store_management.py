import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from zipfile import ZipFile

from fastapi.testclient import TestClient

from backend.main import app


def confirmation(restaurant_name: str, item_name: str) -> dict:
    return {
        "restaurant_name": restaurant_name,
        "categories": [
            {
                "name": "餐點",
                "items": [
                    {
                        "name": item_name,
                        "description": "",
                        "price": 80,
                    }
                ],
            }
        ],
    }


class StoreManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "store-management.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def create_store(self, client: TestClient, name: str, item: str) -> tuple[dict, str]:
        created = client.post(
            "/api/stores", json=confirmation(name, item)
        ).json()
        token = urlsplit(created["management_url"]).fragment.removeprefix("token=")
        return created, token

    def create_order(
        self,
        client: TestClient,
        slug: str,
        name: str,
        *,
        quantity: int = 2,
        note: str = "",
        contact_value: str = "0912345678",
        edit_code: str = "246810",
    ) -> dict:
        response = client.post(
            f"/api/stores/{slug}/orders",
            json={
                "customer_name": name,
                "contact_method": "phone",
                "contact_value": contact_value,
                "edit_code": edit_code,
                "items": [
                    {"item_id": "item-a-a", "quantity": quantity, "note": note}
                ],
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_management_token_returns_only_own_store_customer_orders(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                first, first_token = self.create_store(
                    client, "第一餐館", "第一店便當"
                )
                second, _ = self.create_store(client, "第二餐館", "第二店便當")
                self.create_order(
                    client,
                    first["public_slug"],
                    "小美",
                    quantity=2,
                    note="少飯",
                )
                self.create_order(
                    client,
                    first["public_slug"],
                    "小明",
                    quantity=1,
                    contact_value="0987654321",
                    edit_code="135790",
                )
                self.create_order(client, second["public_slug"], "不應出現")

                response = client.get(
                    f"/api/stores/{first['public_slug']}/management",
                    headers={"Authorization": f"Bearer {first_token}"},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["restaurant_name"], "第一餐館")
        self.assertEqual(data["order_count"], 2)
        self.assertEqual(data["grand_total"], 240)
        self.assertEqual(
            [order["customer_name"] for order in data["orders"]],
            ["小美", "小明"],
        )
        self.assertTrue(
            all(
                order["items"][0]["item_name"] == "第一店便當"
                for order in data["orders"]
            )
        )
        self.assertEqual(len(data["summary"]), 2)
        self.assertEqual(sum(item["total_quantity"] for item in data["summary"]), 3)
        self.assertEqual(sum(item["total_amount"] for item in data["summary"]), 240)
        self.assertEqual([item["note"] for item in data["summary"]], ["少飯", ""])
        self.assertNotIn("management_token", response.text)
        self.assertNotIn("order_access_token", response.text)
        self.assertNotIn("不應出現", response.text)

    def test_wrong_store_or_personal_token_cannot_open_management(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                first, first_token = self.create_store(client, "甲店", "甲餐")
                second, second_token = self.create_store(client, "乙店", "乙餐")
                personal_order = self.create_order(
                    client, first["public_slug"], "顧客"
                )
                personal_token = urlsplit(
                    personal_order["order_url"]
                ).fragment.removeprefix("token=")

                wrong_token = client.get(
                    f"/api/stores/{first['public_slug']}/management",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                other_store_token = client.get(
                    f"/api/stores/{first['public_slug']}/management",
                    headers={"Authorization": f"Bearer {second_token}"},
                )
                customer_token = client.get(
                    f"/api/stores/{first['public_slug']}/management",
                    headers={"Authorization": f"Bearer {personal_token}"},
                )
                valid_first = client.get(
                    f"/api/stores/{first['public_slug']}/management",
                    headers={"Authorization": f"Bearer {first_token}"},
                )

        self.assertEqual(wrong_token.status_code, 403)
        self.assertEqual(other_store_token.status_code, 403)
        self.assertEqual(customer_token.status_code, 403)
        self.assertEqual(valid_first.status_code, 200)

    def test_management_page_contains_no_order_data_before_authorization(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get("/stores/abcdefgh/manage")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("S-ABCDEFGH-001", response.text)
        self.assertNotIn("token=", response.text.lower())

        script = Path("frontend/store-management.js").read_text(encoding="utf-8")
        page = Path("frontend/store-management.html").read_text(encoding="utf-8")
        self.assertIn("store.summary", script)
        self.assertIn("management.xlsx", script)
        self.assertIn("餐點彙整", page)
        self.assertIn("下載 Excel 表格", page)
        self.assertIn("store-management.js?v=20260819-1", page)

    def test_store_can_download_excel_with_summary_and_customer_details(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store, token = self.create_store(client, "表格店", "雞腿便當")
                slug = store["public_slug"]
                self.create_order(client, slug, "小美", quantity=2, note="少飯")
                self.create_order(
                    client,
                    slug,
                    "小華",
                    quantity=1,
                    contact_value="0987654321",
                    edit_code="135790",
                )

                response = client.get(
                    f"/api/stores/{slug}/management.xlsx",
                    headers={"Authorization": f"Bearer {token}"},
                )
                denied = client.get(
                    f"/api/stores/{slug}/management.xlsx",
                    headers={"Authorization": "Bearer wrong-token"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(response.headers["x-order-count"], "2")
        self.assertEqual(response.headers["x-grand-total"], "240")
        self.assertIn(f"store-{slug}-orders.xlsx", response.headers["content-disposition"])
        with ZipFile(BytesIO(response.content)) as workbook:
            self.assertEqual(workbook.testzip(), None)
            workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
            summary_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
            customers_xml = workbook.read("xl/worksheets/sheet2.xml").decode("utf-8")
            details_xml = workbook.read("xl/worksheets/sheet3.xml").decode("utf-8")

        self.assertIn("餐點彙整", workbook_xml)
        self.assertIn("顧客合計", workbook_xml)
        self.assertIn("顧客明細", workbook_xml)
        self.assertIn("雞腿便當", summary_xml)
        self.assertIn("少飯", summary_xml)
        self.assertIn("小美", customers_xml)
        self.assertIn("小華", customers_xml)
        self.assertIn("身分辨識", customers_xml)
        self.assertIn("手機：0912345678", customers_xml)
        self.assertIn("小美", details_xml)
        self.assertIn("小華", details_xml)
        self.assertNotIn(token, response.content.decode("latin-1"))


if __name__ == "__main__":
    unittest.main()
