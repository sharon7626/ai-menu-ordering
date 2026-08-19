import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.menu_recognition import MenuRecognitionResult
from tests.test_menu_upload import VALID_PNG


RECOGNITION = MenuRecognitionResult.model_validate(
    {
        "restaurant_name": "完整流程測試店",
        "categories": [
            {
                "name": "便當",
                "items": [
                    {"name": "雞腿便當", "description": "", "price": 120},
                    {"name": "排骨便當", "description": "", "price": 100},
                ],
            },
            {
                "name": "飲料",
                "items": [
                    {"name": "紅茶", "description": "", "price": 30},
                ],
            },
        ],
        "needs_review": False,
        "warnings": [],
    }
)


class CompleteGroupFlowTests(unittest.TestCase):
    def test_upload_create_two_orders_manage_close_and_keep_demo_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "complete-flow.db"
            database_url = f"sqlite:///{database_path.as_posix()}"
            demo_menu_path = Path("data/menu.json")
            demo_menu_before = demo_menu_path.read_bytes()

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                with patch(
                    "backend.main.recognize_menu",
                    new=AsyncMock(return_value=RECOGNITION),
                ):
                    with TestClient(app) as client:
                        upload_response = client.post(
                            "/api/menu-uploads",
                            files={"file": ("menu.png", VALID_PNG, "image/png")},
                        )
                        self.assertEqual(upload_response.status_code, 200)
                        recognition = upload_response.json()["recognition"]

                        confirmation = {
                            "restaurant_name": recognition["restaurant_name"],
                            "categories": recognition["categories"],
                        }
                        create_response = client.post(
                            "/api/groups",
                            json=confirmation,
                        )
                        self.assertEqual(create_response.status_code, 201)
                        created = create_response.json()
                        code = created["public_code"]
                        management_token = created["management_url"].split(
                            "#token=", 1
                        )[1]

                        public_response = client.get(f"/api/groups/{code}")
                        self.assertEqual(public_response.status_code, 200)
                        public_menu = public_response.json()["menu"]
                        self.assertEqual(
                            public_menu["restaurant"]["name"],
                            "完整流程測試店",
                        )
                        self.assertEqual(len(public_menu["categories"]), 2)
                        chicken_id = public_menu["categories"][0]["items"][0]["id"]
                        tea_id = public_menu["categories"][1]["items"][0]["id"]

                        first_response = client.post(
                            f"/api/groups/{code}/orders",
                            json={
                                "customer_name": "小美",
                                "contact_method": "phone",
                                "contact_value": "0912345678",
                                "edit_code": "246810",
                                "items": [
                                    {"item_id": chicken_id, "quantity": 1},
                                    {"item_id": tea_id, "quantity": 1},
                                ],
                            },
                        )
                        second_response = client.post(
                            f"/api/groups/{code}/orders",
                            json={
                                "customer_name": "小華",
                                "contact_method": "email",
                                "contact_value": "xiaohua@example.com",
                                "edit_code": "135790",
                                "items": [{"item_id": chicken_id, "quantity": 2}],
                            },
                        )
                        self.assertEqual(first_response.status_code, 201)
                        self.assertEqual(second_response.status_code, 201)
                        first = first_response.json()
                        second = second_response.json()
                        self.assertEqual(first["public_order_number"], f"{code}-001")
                        self.assertEqual(second["public_order_number"], f"{code}-002")

                        personal_token = first["order_url"].split("#token=", 1)[1]
                        personal_response = client.get(
                            f"/api/groups/{code}/orders/{first['public_order_number']}",
                            headers={"Authorization": f"Bearer {personal_token}"},
                        )
                        self.assertEqual(personal_response.status_code, 200)
                        self.assertEqual(
                            personal_response.json()["customer_name"],
                            "小美",
                        )

                        management_response = client.get(
                            f"/api/groups/{code}/management",
                            headers={"Authorization": f"Bearer {management_token}"},
                        )
                        self.assertEqual(management_response.status_code, 200)
                        management = management_response.json()
                        self.assertEqual(management["order_count"], 2)
                        self.assertEqual(management["grand_total"], 390)
                        chicken_summary = next(
                            item
                            for item in management["summary"]
                            if item["item_id"] == chicken_id
                        )
                        self.assertEqual(chicken_summary["total_quantity"], 3)
                        self.assertEqual(chicken_summary["total_amount"], 360)

                        legacy_admin = client.get("/api/admin/orders")
                        self.assertEqual(legacy_admin.status_code, 200)
                        self.assertEqual(legacy_admin.json()["orders"], [])

                        close_response = client.post(
                            f"/api/groups/{code}/close",
                            headers={"Authorization": f"Bearer {management_token}"},
                        )
                        self.assertEqual(close_response.status_code, 200)
                        self.assertEqual(close_response.json()["status"], "closed")
                        self.assertIn("狀態：已截止", close_response.json()["text_summary"])

                        late_response = client.post(
                            f"/api/groups/{code}/orders",
                            json={
                                "customer_name": "太晚",
                                "contact_method": "phone",
                                "contact_value": "0912345678",
                                "edit_code": "246810",
                                "items": [{"item_id": tea_id, "quantity": 1}],
                            },
                        )
                        self.assertEqual(late_response.status_code, 409)

                        legacy_order_response = client.post(
                            "/api/orders",
                            json={
                                "customer_name": "示範顧客",
                                "items": [
                                    {
                                        "item_id": "braised-pork-rice",
                                        "item_name": "滷肉飯",
                                        "unit_price": 45,
                                        "quantity": 1,
                                        "subtotal": 45,
                                    }
                                ],
                                "total_amount": 45,
                            },
                        )
                        self.assertEqual(legacy_order_response.status_code, 201)
                        legacy_admin_after = client.get("/api/admin/orders")
                        self.assertEqual(
                            [order["customer_name"] for order in legacy_admin_after.json()["orders"]],
                            ["示範顧客"],
                        )

            self.assertEqual(demo_menu_path.read_bytes(), demo_menu_before)


if __name__ == "__main__":
    unittest.main()
