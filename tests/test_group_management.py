import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import initialize_database, save_group_menu
from backend.group_orders import hash_secret_token
from backend.main import app


MENU = {
    "restaurant": {"name": "統籌測試店"},
    "categories": [
        {
            "id": "category-a",
            "name": "主餐",
            "items": [
                {
                    "id": "item-a-a",
                    "name": "排骨飯",
                    "description": "",
                    "price": 100,
                    "available": True,
                }
            ],
        }
    ],
}


class GroupManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "management.db"
        initialize_database(database_path)
        self.management_token = "private-management-token-for-test"
        save_group_menu(
            public_code="ABC234",
            management_token_hash=hash_secret_token(self.management_token),
            menu=MENU,
            created_at=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc),
            database_path=database_path,
        )
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.personal_token = ""

        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                for name, quantity, note, contact_value in (
                    ("小美", 1, "小辣", "0912345678"),
                    ("小華", 2, "不辣", "0987654321"),
                ):
                    response = client.post(
                        "/api/groups/ABC234/orders",
                        json={
                            "customer_name": name,
                            "contact_method": "phone",
                            "contact_value": contact_value,
                            "items": [
                                {
                                    "item_id": "item-a-a",
                                    "quantity": quantity,
                                    "note": note,
                                }
                            ],
                        },
                    )
                    if not self.personal_token:
                        self.personal_token = response.json()["order_url"].split(
                            "#token=", 1
                        )[1]

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def get_management(self, token: str | None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                return client.get(
                    "/api/groups/ABC234/management",
                    headers=headers,
                )

    def test_management_token_returns_all_personal_orders(self) -> None:
        response = self.get_management(self.management_token)

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["restaurant_name"], "統籌測試店")
        self.assertEqual(result["status"], "open")
        self.assertEqual(len(result["orders"]), 2)
        self.assertEqual(
            [order["customer_name"] for order in result["orders"]],
            ["小美", "小華"],
        )
        self.assertEqual(
            [order["public_order_number"] for order in result["orders"]],
            ["ABC234-001", "ABC234-002"],
        )
        self.assertEqual(result["order_count"], 2)
        self.assertEqual(result["grand_total"], 300)
        self.assertEqual(len(result["summary"]), 2)
        self.assertEqual(result["summary"][0]["item_name"], "排骨飯")
        self.assertEqual(result["summary"][0]["note"], "小辣")
        self.assertEqual(result["summary"][0]["total_quantity"], 1)
        self.assertEqual(result["summary"][0]["total_amount"], 100)
        self.assertEqual(result["summary"][1]["note"], "不辣")
        self.assertEqual(result["summary"][1]["total_quantity"], 2)
        self.assertEqual(result["summary"][1]["total_amount"], 200)
        self.assertIn("【統籌測試店 團購訂單】", result["text_summary"])
        self.assertIn("排骨飯｜小辣 × 1（NT$ 100）", result["text_summary"])
        self.assertIn("排骨飯｜不辣 × 2（NT$ 200）", result["text_summary"])
        self.assertIn("- 小美：", result["text_summary"])
        self.assertNotIn("ABC234-001 小美", result["text_summary"])
        self.assertIn("總金額：NT$ 300", result["text_summary"])
        self.assertNotIn("token", response.text.lower())

    def test_public_code_wrong_token_and_personal_token_cannot_manage(self) -> None:
        responses = [
            self.get_management(None),
            self.get_management("wrong-management-token"),
            self.get_management(self.personal_token),
        ]

        self.assertTrue(all(response.status_code == 403 for response in responses))
        self.assertEqual(len({response.json()["detail"] for response in responses}), 1)

    def test_management_page_contains_no_orders_before_authorization(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get("/groups/ABC234/manage")

        self.assertEqual(response.status_code, 200)
        self.assertIn("團購管理", response.text)
        self.assertNotIn("小美", response.text)
        self.assertNotIn(self.management_token, response.text)

    def test_management_page_offers_grouped_summary_and_excel_download(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        page = (project_root / "frontend" / "group-management.html").read_text(
            encoding="utf-8"
        )
        script = (project_root / "frontend" / "group-management.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="download-excel"', page)
        self.assertIn(
            '<script src="/frontend/group-management.js?v=20260819-1" type="module"></script>',
            page,
        )
        self.assertIn("summariesByItem", script)
        self.assertIn("management.xlsx", script)
        self.assertIn("一般（無備註）", script)
        self.assertIn('cache: "no-store"', script)
        self.assertIn('response.headers.get("X-Order-Count")', script)

    def test_close_group_rejects_new_orders_but_keeps_existing_summary(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                close_response = client.post(
                    "/api/groups/ABC234/close",
                    headers={"Authorization": f"Bearer {self.management_token}"},
                )
                new_order_response = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "截止後",
                        "contact_method": "phone",
                        "contact_value": "0912345678",
                        "items": [{"item_id": "item-a-a", "quantity": 1}],
                    },
                )

        self.assertEqual(close_response.status_code, 200)
        result = close_response.json()
        self.assertEqual(result["status"], "closed")
        self.assertIsNotNone(result["closed_at"])
        self.assertEqual(result["order_count"], 2)
        self.assertEqual(result["grand_total"], 300)
        self.assertIn("狀態：已截止", result["text_summary"])
        self.assertEqual(new_order_response.status_code, 409)

    def test_wrong_token_cannot_close_group(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/groups/ABC234/close",
                    headers={"Authorization": "Bearer wrong-token"},
                )

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
