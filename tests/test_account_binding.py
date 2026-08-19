import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import connect_database
from backend.firebase_auth import AuthenticatedFirebaseUser
from backend.main import app


def confirmation(name: str) -> dict:
    return {
        "restaurant_name": name,
        "categories": [
            {
                "name": "主餐",
                "items": [
                    {"name": "測試餐點", "description": "", "price": 80}
                ],
            }
        ],
    }


def order_payload(name: str) -> dict:
    return {
        "customer_name": name,
        "contact_method": "phone",
        "contact_value": "0912345678",
        "items": [{"item_id": "item-a-a", "quantity": 1, "note": ""}],
    }


class AccountBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "binding.db"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"
        self.user = AuthenticatedFirebaseUser(
            uid="verified-firebase-uid",
            email="person@example.com",
            display_name="登入者",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_logged_in_group_and_orders_bind_only_verified_backend_user(self) -> None:
        headers = {"Authorization": "Bearer verified-token"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    return_value=self.user,
                ):
                    group = client.post(
                        "/api/groups", json=confirmation("登入團購"), headers=headers
                    )
                    code = group.json()["public_code"]
                    group_order = client.post(
                        f"/api/groups/{code}/orders",
                        json=order_payload("團購登入者"),
                        headers=headers,
                    )
                    store = client.post(
                        "/api/stores", json=confirmation("測試店家")
                    )
                    store_order = client.post(
                        f"/api/stores/{store.json()['public_slug']}/orders",
                        json=order_payload("店家登入者"),
                        headers=headers,
                    )

        self.assertEqual(group.status_code, 201)
        self.assertEqual(group_order.status_code, 201)
        self.assertEqual(store_order.status_code, 201)
        connection = connect_database(self.database_path)
        try:
            user = connection.execute(
                "SELECT id, firebase_uid, email, display_name FROM app_users"
            ).fetchone()
            owner = connection.execute(
                "SELECT owner_user_id FROM group_sessions WHERE public_code = ?",
                (code,),
            ).fetchone()
            order_users = connection.execute(
                "SELECT user_id FROM orders ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(user["firebase_uid"], "verified-firebase-uid")
        self.assertEqual(user["email"], "person@example.com")
        self.assertEqual(owner["owner_user_id"], user["id"])
        self.assertEqual([row["user_id"] for row in order_users], [user["id"], user["id"]])

    def test_guest_group_and_order_remain_unassigned(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=confirmation("訪客團購"))
                code = group.json()["public_code"]
                order = client.post(
                    f"/api/groups/{code}/orders",
                    json={**order_payload("訪客"), "edit_code": "246810"},
                )

        self.assertEqual(group.status_code, 201)
        self.assertEqual(order.status_code, 201)
        connection = connect_database(self.database_path)
        try:
            owner = connection.execute(
                "SELECT owner_user_id FROM group_sessions"
            ).fetchone()["owner_user_id"]
            order_user = connection.execute(
                "SELECT user_id FROM orders"
            ).fetchone()["user_id"]
            user_count = connection.execute(
                "SELECT COUNT(*) AS count FROM app_users"
            ).fetchone()["count"]
        finally:
            connection.close()

        self.assertIsNone(owner)
        self.assertIsNone(order_user)
        self.assertEqual(user_count, 0)

    def test_client_cannot_choose_owner_or_order_user_id(self) -> None:
        unsafe_group = confirmation("不可信任欄位") | {"owner_user_id": 999}
        unsafe_order = order_payload("不可信任欄位") | {"user_id": 999}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=unsafe_group)
                valid_group = client.post("/api/groups", json=confirmation("正常團購"))
                order = client.post(
                    f"/api/groups/{valid_group.json()['public_code']}/orders",
                    json=unsafe_order,
                )

        self.assertEqual(group.status_code, 422)
        self.assertEqual(order.status_code, 422)


if __name__ == "__main__":
    unittest.main()
