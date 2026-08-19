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
    "restaurant": {"name": "個人訂單測試店"},
    "categories": [
        {
            "id": "category-a",
            "name": "餐點",
            "items": [
                {
                    "id": "item-a-a",
                    "name": "測試餐點",
                    "description": "",
                    "price": 75,
                    "available": True,
                }
            ],
        }
    ],
}


class PersonalGroupOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "personal-order.db"
        initialize_database(database_path)
        save_group_menu(
            public_code="ABC234",
            management_token_hash=hash_secret_token("management-token"),
            menu=MENU,
            created_at=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc),
            database_path=database_path,
        )
        self.database_url = f"sqlite:///{database_path.as_posix()}"

        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "小美",
                        "contact_method": "email",
                        "contact_value": "xiaomei@example.com",
                        "items": [{"item_id": "item-a-a", "quantity": 2}],
                    },
                )
        result = response.json()
        self.order_number = result["public_order_number"]
        self.token = result["order_url"].split("#token=", 1)[1]

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def get_order(self, token: str | None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                return client.get(
                    f"/api/groups/ABC234/orders/{self.order_number}",
                    headers=headers,
                )

    def test_correct_private_token_returns_only_own_order(self) -> None:
        response = self.get_order(self.token)

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["restaurant_name"], "個人訂單測試店")
        self.assertEqual(result["public_order_number"], "ABC234-001")
        self.assertEqual(result["customer_name"], "小美")
        self.assertEqual(result["total_amount"], 150)
        self.assertEqual(result["items"][0]["quantity"], 2)
        self.assertNotIn("token", response.text.lower())

    def test_public_code_or_wrong_token_cannot_read_order(self) -> None:
        missing_token_response = self.get_order(None)
        wrong_token_response = self.get_order("wrong-private-token")

        self.assertEqual(missing_token_response.status_code, 403)
        self.assertEqual(wrong_token_response.status_code, 403)
        self.assertEqual(
            missing_token_response.json()["detail"],
            wrong_token_response.json()["detail"],
        )

    def test_personal_order_page_contains_no_order_data_before_authorization(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get(
                    f"/groups/ABC234/orders/{self.order_number}"
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("我的訂單", response.text)
        self.assertIn(
            '<script src="/frontend/personal-order.js?v=20260811-2" type="module"></script>',
            response.text,
        )
        self.assertNotIn("小美", response.text)
        self.assertNotIn(self.token, response.text)


if __name__ == "__main__":
    unittest.main()
