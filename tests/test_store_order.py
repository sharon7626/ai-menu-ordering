import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.main import app


def confirmation(restaurant_name: str, item_name: str = "招牌便當") -> dict:
    return {
        "restaurant_name": restaurant_name,
        "categories": [
            {
                "name": "主餐",
                "items": [
                    {
                        "name": item_name,
                        "description": "每日現做",
                        "price": 90,
                    },
                    {
                        "name": "紅茶",
                        "description": "",
                        "price": 25,
                    },
                ],
            }
        ],
    }


class StoreOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "store-order.db"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def create_store(self, client: TestClient, name: str) -> dict:
        response = client.post("/api/stores", json=confirmation(name))
        self.assertEqual(response.status_code, 201)
        return response.json()

    def post_order(
        self,
        client: TestClient,
        slug: str,
        name: str,
        first_quantity: int = 1,
    ):
        return client.post(
            f"/api/stores/{slug}/orders",
            json={
                "customer_name": name,
                "items": [
                    {"item_id": "item-a-a", "quantity": first_quantity},
                    {"item_id": "item-a-b", "quantity": 1},
                ],
            },
        )

    def test_two_customers_receive_distinct_orders_and_own_private_views(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store = self.create_store(client, "安心食堂")
                slug = store["public_slug"]
                first = self.post_order(client, slug, "小美", 2)
                second = self.post_order(client, slug, "小明", 1)

                self.assertEqual(first.status_code, 201)
                self.assertEqual(second.status_code, 201)
                first_data = first.json()
                second_data = second.json()
                self.assertEqual(first_data["total_amount"], 205)
                self.assertEqual(first_data["public_order_number"], f"S-{slug.upper()}-001")
                self.assertEqual(second_data["public_order_number"], f"S-{slug.upper()}-002")

                first_url = urlsplit(first_data["order_url"])
                first_token = first_url.fragment.removeprefix("token=")
                personal = client.get(
                    first_url.path.replace("/stores/", "/api/stores/", 1),
                    headers={"Authorization": f"Bearer {first_token}"},
                )
                wrong_token = client.get(
                    first_url.path.replace("/stores/", "/api/stores/", 1),
                    headers={"Authorization": "Bearer wrong-token"},
                )

        self.assertEqual(personal.status_code, 200)
        self.assertEqual(personal.json()["customer_name"], "小美")
        self.assertEqual(len(personal.json()["items"]), 2)
        self.assertEqual(wrong_token.status_code, 403)
        self.assertNotIn("token=", first_url.path)

    def test_order_cannot_cross_stores_or_trust_unknown_item(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                first_store = self.create_store(client, "第一家")
                second_store = self.create_store(client, "第二家")
                created = self.post_order(
                    client, first_store["public_slug"], "顧客甲"
                ).json()
                split_url = urlsplit(created["order_url"])
                token = split_url.fragment.removeprefix("token=")
                cross_store = client.get(
                    f"/api/stores/{second_store['public_slug']}/orders/"
                    f"{created['public_order_number']}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                invalid_item = client.post(
                    f"/api/stores/{first_store['public_slug']}/orders",
                    json={
                        "customer_name": "顧客乙",
                        "items": [{"item_id": "item-not-found", "quantity": 1}],
                    },
                )

        self.assertEqual(cross_store.status_code, 403)
        self.assertEqual(invalid_item.status_code, 422)

    def test_inactive_store_rejects_new_orders_without_advancing_sequence(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store = self.create_store(client, "休息中的店")
                connection = sqlite3.connect(self.database_path)
                connection.execute(
                    "UPDATE store_profiles SET active = 0 WHERE public_slug = ?",
                    (store["public_slug"],),
                )
                connection.commit()
                connection.close()
                rejected = self.post_order(client, store["public_slug"], "小華")

                connection = sqlite3.connect(self.database_path)
                sequence = connection.execute(
                    "SELECT next_order_sequence FROM store_profiles WHERE public_slug = ?",
                    (store["public_slug"],),
                ).fetchone()[0]
                connection.close()

        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(sequence, 1)

    def test_personal_page_contains_no_order_or_token_before_authorization(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get(
                    "/stores/abcdefgh/orders/S-ABCDEFGH-001"
                )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("S-ABCDEFGH-001", response.text)
        self.assertNotIn("token=", response.text.lower())


if __name__ == "__main__":
    unittest.main()
