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


PROJECT_ROOT = Path(__file__).resolve().parent.parent


MENU = {
    "restaurant": {"name": "測試餐廳"},
    "categories": [
        {
            "id": "category-a",
            "name": "主餐",
            "items": [
                {
                    "id": "item-a-a",
                    "name": "測試餐點",
                    "description": "",
                    "price": 80,
                    "available": True,
                }
            ],
        }
    ],
}


def group_payload(
    *,
    name: str = "測試者",
    note: str = "",
    website: str = "",
    contact_value: str = "0912-345-678",
    repeat_action: str | None = None,
) -> dict:
    payload = {
        "customer_name": name,
        "contact_method": "phone",
        "contact_value": contact_value,
        "edit_code": "246810",
        "website": website,
        "items": [{"item_id": "item-a-a", "quantity": 1, "note": note}],
    }
    if repeat_action is not None:
        payload["repeat_action"] = repeat_action
    return payload


def store_payload(**kwargs) -> dict:
    return group_payload(**kwargs)


def store_confirmation() -> dict:
    return {
        "restaurant_name": "測試店家",
        "categories": [
            {
                "name": "主餐",
                "items": [
                    {
                        "name": "測試餐點",
                        "description": "",
                        "price": 80,
                    }
                ],
            }
        ],
    }


class OrderAbuseProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "abuse-protection.db"
        initialize_database(self.database_path)
        save_group_menu(
            public_code="ABC234",
            management_token_hash=hash_secret_token("management-token"),
            menu=MENU,
            created_at=datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc),
            database_path=self.database_path,
        )
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_group_repeat_submission_requires_an_action(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                first = client.post("/api/groups/ABC234/orders", json=group_payload())
                duplicate = client.post("/api/groups/ABC234/orders", json=group_payload())

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(
            duplicate.json()["detail"]["code"], "ORDER_ACTION_REQUIRED"
        )
        self.assertEqual(
            duplicate.json()["detail"]["public_order_number"], "ABC234-001"
        )

    def test_group_rate_limits_sixth_distinct_order(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                accepted = [
                    client.post(
                        "/api/groups/ABC234/orders",
                        json=group_payload(name="測試者", note="第0筆"),
                    )
                ]
                for i in range(1, 5):
                    accepted.append(
                        client.post(
                            "/api/groups/ABC234/orders",
                            json=group_payload(
                                name="測試者",
                                note=f"第{i}筆",
                                repeat_action="replace",
                            ),
                        )
                    )
                limited = client.post(
                    "/api/groups/ABC234/orders",
                    json=group_payload(
                        name="測試者",
                        note="第六筆",
                        repeat_action="replace",
                    ),
                )

        self.assertEqual(accepted[0].status_code, 201)
        self.assertTrue(all(response.status_code == 200 for response in accepted[1:]))
        self.assertEqual(limited.status_code, 429)
        self.assertIn("次數過多", limited.json()["detail"])
        self.assertGreater(int(limited.headers["Retry-After"]), 0)

    def test_group_rejects_filled_honeypot(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/groups/ABC234/orders",
                    json=group_payload(website="https://spam.example"),
                )

        self.assertEqual(response.status_code, 422)

    def test_store_rejects_duplicate_submission(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store = client.post("/api/stores", json=store_confirmation()).json()
                endpoint = f"/api/stores/{store['public_slug']}/orders"
                first = client.post(endpoint, json=store_payload())
                client.cookies.clear()
                duplicate = client.post(endpoint, json=store_payload())

        self.assertEqual(first.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("重複送單", duplicate.json()["detail"])

    def test_store_rate_limits_sixth_distinct_order(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store = client.post("/api/stores", json=store_confirmation()).json()
                endpoint = f"/api/stores/{store['public_slug']}/orders"
                accepted = [client.post(endpoint, json=store_payload(note="第0筆"))]
                for i in range(1, 5):
                    accepted.append(
                        client.post(
                            endpoint,
                            json=store_payload(
                                note=f"第{i}筆", repeat_action="replace"
                            ),
                        )
                    )
                limited = client.post(
                    endpoint,
                    json=store_payload(note="第六筆", repeat_action="replace"),
                )

        self.assertEqual(accepted[0].status_code, 201)
        self.assertTrue(all(response.status_code == 200 for response in accepted[1:]))
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited.headers["Retry-After"]), 0)

    def test_store_rejects_filled_honeypot(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store = client.post("/api/stores", json=store_confirmation()).json()
                response = client.post(
                    f"/api/stores/{store['public_slug']}/orders",
                    json=store_payload(website="bot-filled-this-field"),
                )

        self.assertEqual(response.status_code, 422)

    def test_group_page_sends_empty_honeypot_field(self) -> None:
        page = (PROJECT_ROOT / "frontend" / "group.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "frontend" / "group.js").read_text(encoding="utf-8")

        self.assertIn('id="order-website"', page)
        self.assertIn("website: orderWebsite.value", script)

    def test_store_page_sends_empty_honeypot_field(self) -> None:
        page = (PROJECT_ROOT / "frontend" / "store.html").read_text(encoding="utf-8")
        script = (PROJECT_ROOT / "frontend" / "store.js").read_text(encoding="utf-8")

        self.assertIn('id="order-website"', page)
        self.assertIn("website: orderWebsite.value", script)
        self.assertIn('id="edit-code"', page)
        self.assertIn('id="recover-order"', page)
        self.assertIn("/orders/recover", script)
        self.assertIn("repeat_action", script)


if __name__ == "__main__":
    unittest.main()
