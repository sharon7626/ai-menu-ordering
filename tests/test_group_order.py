import hashlib
import os
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import connect_database, initialize_database, save_group_menu
from backend.group_orders import hash_secret_token
from backend.main import app


GROUP_MENU = {
    "restaurant": {"name": "團購便當店"},
    "categories": [
        {
            "id": "category-a",
            "name": "便當",
            "items": [
                {
                    "id": "item-a-a",
                    "name": "雞腿便當",
                    "description": "",
                    "price": 120,
                    "available": True,
                },
                {
                    "id": "item-a-b",
                    "name": "停售便當",
                    "description": "",
                    "price": 90,
                    "available": False,
                },
                {
                    "id": "item-a-c",
                    "name": "排骨便當",
                    "description": "",
                    "price": 100,
                    "available": True,
                },
            ],
        }
    ],
}


class GroupOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "group-orders.db"
        initialize_database(self.database_path)
        self.first_group_id = save_group_menu(
            public_code="ABC234",
            management_token_hash=hash_secret_token("first-management-token"),
            menu=GROUP_MENU,
            created_at=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc),
            database_path=self.database_path,
        )
        self.second_group_id = save_group_menu(
            public_code="XYZ567",
            management_token_hash=hash_secret_token("second-management-token"),
            menu=GROUP_MENU,
            created_at=datetime(2026, 8, 7, 6, 31, tzinfo=timezone.utc),
            database_path=self.database_path,
        )
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def post_order(
        self,
        code: str,
        name: str,
        quantity: int = 1,
        contact_value: str = "0912345678",
    ):
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                return client.post(
                    f"/api/groups/{code}/orders",
                    json={
                        "customer_name": name,
                        "contact_method": "phone",
                        "contact_value": contact_value,
                        "edit_code": "246810",
                        "items": [{"item_id": "item-a-a", "quantity": quantity}],
                    },
                )

    def test_two_participants_receive_distinct_numbers_and_server_prices(self) -> None:
        first_response = self.post_order("ABC234", "小美", quantity=2)
        second_response = self.post_order(
            "ABC234", "小華", quantity=1, contact_value="0987654321"
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        first = first_response.json()
        second = second_response.json()
        self.assertEqual(first["public_order_number"], "ABC234-001")
        self.assertEqual(second["public_order_number"], "ABC234-002")
        self.assertEqual(first["total_amount"], 240)
        self.assertEqual(first["items"][0]["unit_price"], 120)

        token_match = re.search(r"#token=(.+)$", first["order_url"])
        self.assertIsNotNone(token_match)
        raw_token = token_match.group(1)

        connection = connect_database(self.database_path)
        try:
            rows = connection.execute(
                """
                SELECT
                    group_session_id,
                    public_order_number,
                    order_access_token_hash,
                    guest_edit_code_hash,
                    customer_name,
                    total_amount
                FROM orders
                ORDER BY id
                """
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["group_session_id"] == self.first_group_id for row in rows))
        self.assertEqual(rows[0]["customer_name"], "小美")
        self.assertEqual(rows[0]["total_amount"], 240)
        self.assertEqual(
            rows[0]["order_access_token_hash"],
            hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn(raw_token, str(dict(rows[0])))
        self.assertEqual(
            rows[0]["guest_edit_code_hash"],
            hashlib.sha256("246810".encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("246810", str(dict(rows[0])))

    def test_orders_do_not_cross_between_groups(self) -> None:
        first_response = self.post_order("ABC234", "第一團", quantity=1)
        second_response = self.post_order("XYZ567", "第二團", quantity=1)

        self.assertEqual(first_response.json()["public_order_number"], "ABC234-001")
        self.assertEqual(second_response.json()["public_order_number"], "XYZ567-001")

        connection = connect_database(self.database_path)
        try:
            memberships = connection.execute(
                """
                SELECT public_order_number, group_session_id
                FROM orders
                ORDER BY public_order_number
                """
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(memberships[0]["group_session_id"], self.first_group_id)
        self.assertEqual(memberships[1]["group_session_id"], self.second_group_id)

    def test_same_identity_adds_or_replaces_one_existing_order(self) -> None:
        payload = {
            "customer_name": "小美",
            "contact_method": "phone",
            "contact_value": "0912345678",
            "edit_code": "246810",
            "items": [{"item_id": "item-a-a", "quantity": 1}],
        }
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                first = client.post("/api/groups/ABC234/orders", json=payload)
                action_required = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        **payload,
                        "items": [
                            {
                                "item_id": "item-a-c",
                                "quantity": 1,
                                "note": "不要辣",
                            }
                        ],
                    },
                )
                added = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        **payload,
                        "repeat_action": "add",
                        "items": [
                            {
                                "item_id": "item-a-c",
                                "quantity": 1,
                                "note": "不要辣",
                            }
                        ],
                    },
                )
                replaced = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        **payload,
                        "repeat_action": "replace",
                        "items": [{"item_id": "item-a-a", "quantity": 2}],
                    },
                )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(action_required.status_code, 409)
        self.assertEqual(
            action_required.json()["detail"]["code"], "ORDER_ACTION_REQUIRED"
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(
            {
                first.json()["public_order_number"],
                added.json()["public_order_number"],
                replaced.json()["public_order_number"],
            },
            {"ABC234-001"},
        )
        self.assertEqual(
            {item["item_id"] for item in added.json()["items"]},
            {"item-a-a", "item-a-c"},
        )
        self.assertEqual(replaced.json()["total_amount"], 240)
        self.assertEqual(len(replaced.json()["items"]), 1)
        self.assertEqual(replaced.json()["items"][0]["quantity"], 2)

        connection = connect_database(self.database_path)
        try:
            order_count = connection.execute(
                "SELECT COUNT(*) FROM orders WHERE group_session_id = ?",
                (self.first_group_id,),
            ).fetchone()[0]
            next_sequence = connection.execute(
                "SELECT next_order_sequence FROM group_sessions WHERE id = ?",
                (self.first_group_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(order_count, 1)
        self.assertEqual(next_sequence, 2)

    def test_same_identity_on_another_device_cannot_replace_by_phone_alone(self) -> None:
        first = self.post_order("ABC234", "小美")
        self.assertEqual(first.status_code, 201)

        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as another_device:
                existing = another_device.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "冒用者",
                        "contact_method": "phone",
                        "contact_value": "0912345678",
                        "items": [{"item_id": "item-a-c", "quantity": 1}],
                    },
                )
                forbidden = another_device.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "冒用者",
                        "contact_method": "phone",
                        "contact_value": "0912345678",
                        "repeat_action": "replace",
                        "items": [{"item_id": "item-a-c", "quantity": 1}],
                    },
                )

        self.assertEqual(existing.status_code, 409)
        self.assertEqual(existing.json()["detail"]["code"], "ORDER_ALREADY_EXISTS")
        self.assertEqual(forbidden.status_code, 403)

    def test_guest_can_recover_and_replace_same_order_with_edit_code(self) -> None:
        first = self.post_order("ABC234", "小美")
        self.assertEqual(first.status_code, 201)

        recovery_payload = {
            "contact_method": "phone",
            "contact_value": "0912345678",
            "edit_code": "246810",
        }
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as another_device:
                recovered = another_device.post(
                    "/api/groups/ABC234/orders/recover", json=recovery_payload
                )
                replaced = another_device.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "換裝置的小美",
                        **recovery_payload,
                        "repeat_action": "replace",
                        "items": [{"item_id": "item-a-c", "quantity": 2}],
                    },
                )

        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["public_order_number"], "ABC234-001")
        self.assertEqual(recovered.json()["items"][0]["item_id"], "item-a-a")
        self.assertEqual(replaced.status_code, 200)
        self.assertEqual(replaced.json()["public_order_number"], "ABC234-001")
        self.assertEqual(replaced.json()["items"][0]["item_id"], "item-a-c")
        self.assertEqual(replaced.json()["total_amount"], 200)

        connection = connect_database(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM orders WHERE group_session_id = ?",
                (self.first_group_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 1)

    def test_wrong_edit_code_is_rate_limited_and_cannot_recover(self) -> None:
        first = self.post_order("ABC234", "小美")
        self.assertEqual(first.status_code, 201)

        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as another_device:
                responses = [
                    another_device.post(
                        "/api/groups/ABC234/orders/recover",
                        json={
                            "contact_method": "phone",
                            "contact_value": "0912345678",
                            "edit_code": f"{attempt:06d}",
                        },
                    )
                    for attempt in range(1, 6)
                ]

        self.assertTrue(all(response.status_code == 403 for response in responses[:4]))
        self.assertEqual(responses[4].status_code, 429)
        self.assertIn("Retry-After", responses[4].headers)

    def test_new_guest_order_requires_six_digit_edit_code(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "未設修改碼",
                        "contact_method": "phone",
                        "contact_value": "0912345678",
                        "items": [{"item_id": "item-a-a", "quantity": 1}],
                    },
                )
        self.assertEqual(response.status_code, 422)
        self.assertIn("6 碼", response.json()["detail"])

    def test_closed_group_rejects_new_order_without_advancing_sequence(self) -> None:
        connection = connect_database(self.database_path)
        try:
            connection.execute(
                """
                UPDATE group_sessions
                SET status = 'closed', closed_at = ?
                WHERE id = ?
                """,
                ("2026-08-07T07:00:00+00:00", self.first_group_id),
            )
            connection.commit()
        finally:
            connection.close()

        response = self.post_order("ABC234", "太晚送單")
        self.assertEqual(response.status_code, 409)
        self.assertIn("已截止", response.json()["detail"])

        connection = connect_database(self.database_path)
        try:
            group = connection.execute(
                "SELECT next_order_sequence FROM group_sessions WHERE id = ?",
                (self.first_group_id,),
            ).fetchone()
            order_count = connection.execute(
                "SELECT COUNT(*) FROM orders WHERE group_session_id = ?",
                (self.first_group_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(group["next_order_sequence"], 1)
        self.assertEqual(order_count, 0)

    def test_unknown_or_unavailable_item_is_rejected(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                unavailable_response = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "測試者",
                        "contact_method": "phone",
                        "contact_value": "0912345678",
                        "items": [{"item_id": "item-a-b", "quantity": 1}],
                    },
                )
                forged_price_response = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "測試者",
                        "contact_method": "phone",
                        "contact_value": "0912345678",
                        "items": [
                            {
                                "item_id": "item-a-a",
                                "quantity": 1,
                                "unit_price": 1,
                            }
                        ],
                    },
                )

        self.assertEqual(unavailable_response.status_code, 422)
        self.assertIn("暫停供應", unavailable_response.json()["detail"])
        self.assertEqual(forged_price_response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
