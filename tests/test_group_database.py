import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import connect_database, initialize_database


MENU_ONE = {
    "restaurant": {"name": "第一家餐廳"},
    "categories": [
        {
            "id": "main-dishes",
            "name": "主餐",
            "items": [
                {
                    "id": "pork-rice",
                    "name": "滷肉飯",
                    "description": "",
                    "price": 60,
                    "available": True,
                }
            ],
        }
    ],
}

MENU_TWO = {
    "restaurant": {"name": "第二家餐廳"},
    "categories": [
        {
            "id": "drinks",
            "name": "飲料",
            "items": [
                {
                    "id": "black-tea",
                    "name": "紅茶",
                    "description": "",
                    "price": 30,
                    "available": True,
                }
            ],
        }
    ],
}


class GroupDatabaseTests(unittest.TestCase):
    def test_two_groups_keep_menus_and_orders_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "groups.db"
            initialize_database(database_path)

            connection = connect_database(database_path)
            try:
                first_group_id = connection.execute(
                    """
                    INSERT INTO group_sessions (
                        public_code,
                        management_token_hash,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    ("ABC234", "a" * 64, "2026-08-07T06:30:00+00:00"),
                ).lastrowid
                second_group_id = connection.execute(
                    """
                    INSERT INTO group_sessions (
                        public_code,
                        management_token_hash,
                        created_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    ("XYZ567", "b" * 64, "2026-08-07T06:31:00+00:00"),
                ).lastrowid

                connection.executemany(
                    """
                    INSERT INTO group_menus (group_session_id, menu_json, created_at)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (
                            first_group_id,
                            json.dumps(MENU_ONE, ensure_ascii=False),
                            "2026-08-07T06:30:00+00:00",
                        ),
                        (
                            second_group_id,
                            json.dumps(MENU_TWO, ensure_ascii=False),
                            "2026-08-07T06:31:00+00:00",
                        ),
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO orders (
                        group_session_id,
                        public_order_number,
                        order_access_token_hash,
                        customer_name,
                        total_amount,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            first_group_id,
                            "ABC234-001",
                            "c" * 64,
                            "小美",
                            60,
                            "2026-08-07T06:35:00+00:00",
                        ),
                        (
                            second_group_id,
                            "XYZ567-001",
                            "d" * 64,
                            "小華",
                            30,
                            "2026-08-07T06:36:00+00:00",
                        ),
                    ],
                )
                connection.commit()

                first_group = connection.execute(
                    """
                    SELECT group_menus.menu_json, orders.customer_name
                    FROM group_sessions
                    JOIN group_menus
                        ON group_menus.group_session_id = group_sessions.id
                    JOIN orders ON orders.group_session_id = group_sessions.id
                    WHERE group_sessions.public_code = ?
                    """,
                    ("ABC234",),
                ).fetchone()
                second_group = connection.execute(
                    """
                    SELECT group_menus.menu_json, orders.customer_name
                    FROM group_sessions
                    JOIN group_menus
                        ON group_menus.group_session_id = group_sessions.id
                    JOIN orders ON orders.group_session_id = group_sessions.id
                    WHERE group_sessions.public_code = ?
                    """,
                    ("XYZ567",),
                ).fetchone()

                self.assertEqual(first_group["customer_name"], "小美")
                self.assertEqual(
                    json.loads(first_group["menu_json"])["restaurant"]["name"],
                    "第一家餐廳",
                )
                self.assertEqual(second_group["customer_name"], "小華")
                self.assertEqual(
                    json.loads(second_group["menu_json"])["restaurant"]["name"],
                    "第二家餐廳",
                )
            finally:
                connection.close()

    def test_group_constraints_reject_invalid_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "group-constraints.db"
            initialize_database(database_path)

            connection = connect_database(database_path)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO group_menus (group_session_id, menu_json, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (999, json.dumps(MENU_ONE), "2026-08-07T06:30:00+00:00"),
                    )
            finally:
                connection.close()

    def test_existing_orders_are_preserved_when_group_columns_are_added(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy-orders.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        customer_name TEXT NOT NULL,
                        total_amount INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO orders (customer_name, total_amount, created_at)
                    VALUES (?, ?, ?)
                    """,
                    ("舊訂單", 100, "2026-08-04T12:00:00+00:00"),
                )
                connection.commit()
            finally:
                connection.close()

            initialize_database(database_path)
            initialize_database(database_path)

            connection = connect_database(database_path)
            try:
                columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(orders)")
                }
                saved_order = connection.execute(
                    """
                    SELECT customer_name, group_session_id, public_order_number
                    FROM orders
                    """
                ).fetchone()

                self.assertTrue(
                    {
                        "group_session_id",
                        "public_order_number",
                        "order_access_token_hash",
                    }.issubset(columns)
                )
                self.assertEqual(saved_order["customer_name"], "舊訂單")
                self.assertIsNone(saved_order["group_session_id"])
                self.assertIsNone(saved_order["public_order_number"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
