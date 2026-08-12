import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.firebase_auth import AuthenticatedFirebaseUser
from backend.main import app


MENU = {
    "restaurant_name": "訂單測試店",
    "categories": [
        {
            "name": "餐點",
            "items": [{"name": "測試餐", "description": "", "price": 70}],
        }
    ],
}
ORDER = {
    "customer_name": "測試者",
    "items": [{"item_id": "item-a-a", "quantity": 1, "note": ""}],
}


class MyOrdersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "my-orders.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.user_a = AuthenticatedFirebaseUser("uid-a", "a@example.com", "使用者 A")
        self.user_b = AuthenticatedFirebaseUser("uid-b", "b@example.com", "使用者 B")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def verified_user(self, token: str) -> AuthenticatedFirebaseUser:
        return self.user_a if token == "token-a" else self.user_b

    def test_my_orders_include_only_current_users_group_and_store_orders(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        headers_b = {"Authorization": "Bearer token-b"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    group = client.post("/api/groups", json=MENU).json()
                    store = client.post("/api/stores", json=MENU).json()
                    group_order_a = client.post(
                        f"/api/groups/{group['public_code']}/orders",
                        json=ORDER,
                        headers=headers_a,
                    ).json()
                    store_order_a = client.post(
                        f"/api/stores/{store['public_slug']}/orders",
                        json=ORDER,
                        headers=headers_a,
                    ).json()
                    group_order_b = client.post(
                        f"/api/groups/{group['public_code']}/orders",
                        json=ORDER,
                        headers=headers_b,
                    ).json()
                    client.post(
                        f"/api/groups/{group['public_code']}/orders",
                        json=ORDER,
                    )
                    mine = client.get("/api/me/orders", headers=headers_a)
                    group_archive_url = next(
                        order["archive_api_url"]
                        for order in mine.json()["orders"]
                        if order["mode"] == "group"
                    )
                    store_archive_url = next(
                        order["archive_api_url"]
                        for order in mine.json()["orders"]
                        if order["mode"] == "store"
                    )
                    archived_group = client.post(
                        f"{group_archive_url}/archive", headers=headers_a
                    )
                    archived_store = client.post(
                        f"{store_archive_url}/archive", headers=headers_a
                    )
                    active_after_archive = client.get(
                        "/api/me/orders", headers=headers_a
                    )
                    archived_list = client.get(
                        "/api/me/orders?archived=true", headers=headers_a
                    )
                    other_restore = client.post(
                        f"{group_archive_url}/restore", headers=headers_b
                    )
                    restored_group = client.post(
                        f"{group_archive_url}/restore", headers=headers_a
                    )
                    restored_store = client.post(
                        f"{store_archive_url}/restore", headers=headers_a
                    )
                    active_after_restore = client.get(
                        "/api/me/orders", headers=headers_a
                    )
                    own_group = client.get(
                        f"/api/me/group-orders/{group['public_code']}/{group_order_a['public_order_number']}",
                        headers=headers_a,
                    )
                    own_store = client.get(
                        f"/api/me/store-orders/{store['public_slug']}/{store_order_a['public_order_number']}",
                        headers=headers_a,
                    )
                    other = client.get(
                        f"/api/me/group-orders/{group['public_code']}/{group_order_b['public_order_number']}",
                        headers=headers_a,
                    )

        self.assertEqual(mine.status_code, 200)
        self.assertEqual({order["mode"] for order in mine.json()["orders"]}, {"group", "store"})
        self.assertEqual(len(mine.json()["orders"]), 2)
        self.assertNotIn("token", mine.text.lower())
        self.assertEqual(archived_group.status_code, 200)
        self.assertEqual(archived_store.status_code, 200)
        self.assertEqual(active_after_archive.json()["orders"], [])
        self.assertEqual(len(archived_list.json()["orders"]), 2)
        self.assertEqual(other_restore.status_code, 403)
        self.assertEqual(restored_group.status_code, 200)
        self.assertEqual(restored_store.status_code, 200)
        self.assertEqual(len(active_after_restore.json()["orders"]), 2)
        self.assertEqual(own_group.status_code, 200)
        self.assertEqual(own_store.status_code, 200)
        self.assertEqual(other.status_code, 403)

    def test_existing_order_token_still_works(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=MENU).json()
                with patch(
                    "backend.main.verify_firebase_id_token",
                    return_value=self.user_a,
                ):
                    created = client.post(
                        f"/api/groups/{group['public_code']}/orders",
                        json=ORDER,
                        headers=headers_a,
                    ).json()
                token = urlsplit(created["order_url"]).fragment.removeprefix("token=")
                response = client.get(
                    f"/api/groups/{group['public_code']}/orders/{created['public_order_number']}",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["public_order_number"], created["public_order_number"])

    def test_my_orders_page_is_available(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                page = client.get("/me/orders")
        self.assertEqual(page.status_code, 200)
        self.assertIn("我的訂單", page.text)
        self.assertIn("我的店家固定菜單", page.text)
        self.assertIn("我送出的訂單", page.text)
        self.assertIn("找回以前建立的店家固定菜單", page.text)
        self.assertIn(
            '<script src="/frontend/my-orders.js?v=20260812-4" type="module"></script>',
            page.text,
        )
        script = Path("frontend/my-orders.js").read_text(encoding="utf-8")
        self.assertIn("封存訂單", script)
        self.assertIn("恢復訂單", script)
        self.assertIn('fetch("/api/me/menus"', script)
        self.assertIn("店家固定菜單", script)
        self.assertIn("X-Management-Token", script)


if __name__ == "__main__":
    unittest.main()
