import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.main import app
from backend.menu_recognition import MenuRecognitionResult
from tests.test_menu_upload import VALID_PNG


RECOGNITION = MenuRecognitionResult.model_validate(
    {
        "restaurant_name": "店家完整流程測試店",
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


class CompleteStoreAndDualModeFlowTests(unittest.TestCase):
    def test_store_flow_and_group_flow_remain_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "store-flow.db"
            database_url = f"sqlite:///{database_path.as_posix()}"
            demo_menu_path = Path("data/menu.json")
            demo_menu_before = demo_menu_path.read_bytes()

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                with patch(
                    "backend.main.recognize_menu",
                    new=AsyncMock(return_value=RECOGNITION),
                ):
                    with TestClient(app) as client:
                        upload = client.post(
                            "/api/menu-uploads",
                            files={"file": ("menu.png", VALID_PNG, "image/png")},
                        )
                        self.assertEqual(upload.status_code, 200)
                        recognized = upload.json()["recognition"]
                        confirmation = {
                            "restaurant_name": recognized["restaurant_name"],
                            "categories": recognized["categories"],
                        }

                        store_response = client.post(
                            "/api/stores", json=confirmation
                        )
                        self.assertEqual(store_response.status_code, 201)
                        store = store_response.json()
                        slug = store["public_slug"]
                        management_token = urlsplit(
                            store["management_url"]
                        ).fragment.removeprefix("token=")

                        public_store = client.get(f"/api/stores/{slug}")
                        qr_response = client.get(f"/api/stores/{slug}/qr.svg")
                        self.assertEqual(public_store.status_code, 200)
                        self.assertEqual(qr_response.status_code, 200)
                        self.assertEqual(
                            public_store.json()["menu"]["restaurant"]["name"],
                            "店家完整流程測試店",
                        )
                        self.assertNotIn("token", public_store.text.lower())
                        chicken_id = public_store.json()["menu"]["categories"][0][
                            "items"
                        ][0]["id"]
                        tea_id = public_store.json()["menu"]["categories"][1][
                            "items"
                        ][0]["id"]

                        first_response = client.post(
                            f"/api/stores/{slug}/orders",
                            json={
                                "customer_name": "小美",
                                "contact_method": "phone",
                                "contact_value": "0912345678",
                                "items": [
                                    {"item_id": chicken_id, "quantity": 1},
                                    {"item_id": tea_id, "quantity": 1},
                                ],
                            },
                        )
                        second_response = client.post(
                            f"/api/stores/{slug}/orders",
                            json={
                                "customer_name": "小華",
                                "contact_method": "email",
                                "contact_value": "xiaohua@example.com",
                                "items": [{"item_id": chicken_id, "quantity": 2}],
                            },
                        )
                        self.assertEqual(first_response.status_code, 201)
                        self.assertEqual(second_response.status_code, 201)
                        first = first_response.json()
                        second = second_response.json()
                        self.assertEqual(
                            first["public_order_number"], f"S-{slug.upper()}-001"
                        )
                        self.assertEqual(
                            second["public_order_number"], f"S-{slug.upper()}-002"
                        )

                        personal_url = urlsplit(first["order_url"])
                        personal = client.get(
                            personal_url.path.replace("/stores/", "/api/stores/", 1),
                            headers={
                                "Authorization":
                                f"Bearer {personal_url.fragment.removeprefix('token=')}"
                            },
                        )
                        self.assertEqual(personal.status_code, 200)
                        self.assertEqual(personal.json()["customer_name"], "小美")

                        store_management = client.get(
                            f"/api/stores/{slug}/management",
                            headers={"Authorization": f"Bearer {management_token}"},
                        )
                        self.assertEqual(store_management.status_code, 200)
                        managed = store_management.json()
                        self.assertEqual(managed["order_count"], 2)
                        self.assertEqual(managed["grand_total"], 390)
                        self.assertEqual(
                            [order["customer_name"] for order in managed["orders"]],
                            ["小美", "小華"],
                        )

                        group_response = client.post(
                            "/api/groups", json=confirmation
                        )
                        self.assertEqual(group_response.status_code, 201)
                        group_code = group_response.json()["public_code"]
                        group_order = client.post(
                            f"/api/groups/{group_code}/orders",
                            json={
                                "customer_name": "團購顧客",
                                "contact_method": "phone",
                                "contact_value": "0912345678",
                                "items": [{"item_id": chicken_id, "quantity": 1}],
                            },
                        )
                        self.assertEqual(group_order.status_code, 201)
                        self.assertEqual(
                            group_order.json()["public_order_number"],
                            f"{group_code}-001",
                        )

                        store_management_after_group = client.get(
                            f"/api/stores/{slug}/management",
                            headers={"Authorization": f"Bearer {management_token}"},
                        ).json()
                        self.assertEqual(
                            store_management_after_group["order_count"], 2
                        )
                        self.assertNotIn(
                            "團購顧客", str(store_management_after_group)
                        )
                        legacy_admin = client.get("/api/admin/orders").json()
                        self.assertEqual(legacy_admin["orders"], [])

            self.assertEqual(demo_menu_path.read_bytes(), demo_menu_before)


if __name__ == "__main__":
    unittest.main()
