import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.database import connect_database, initialize_database


LEGACY_TABLES = """
CREATE TABLE group_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_code TEXT NOT NULL UNIQUE,
    management_token_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    next_order_sequence INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_session_id INTEGER,
    store_profile_id INTEGER,
    public_order_number TEXT,
    order_access_token_hash TEXT,
    customer_name TEXT NOT NULL,
    total_amount INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    subtotal INTEGER NOT NULL
);
"""


class AccountSchemaTests(unittest.TestCase):
    def test_fresh_database_has_user_table_nullable_relations_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "fresh-account.db"
            initialize_database(database_path)
            connection = connect_database(database_path)
            try:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                group_columns = {
                    row["name"]: row
                    for row in connection.execute("PRAGMA table_info(group_sessions)")
                }
                order_columns = {
                    row["name"]: row
                    for row in connection.execute("PRAGMA table_info(orders)")
                }
                indexes = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                }
            finally:
                connection.close()

        self.assertIn("app_users", tables)
        self.assertEqual(group_columns["owner_user_id"]["notnull"], 0)
        self.assertEqual(group_columns["archived_at"]["notnull"], 0)
        self.assertEqual(order_columns["user_id"]["notnull"], 0)
        self.assertEqual(order_columns["archived_at"]["notnull"], 0)
        self.assertIn("idx_group_sessions_owner_created_at", indexes)
        self.assertIn("idx_orders_user_created_at", indexes)

    def test_legacy_rows_are_preserved_and_not_assigned_to_any_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "legacy-account.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.executescript(LEGACY_TABLES)
                connection.execute(
                    """
                    INSERT INTO group_sessions (
                        public_code, management_token_hash, status,
                        next_order_sequence, created_at, closed_at
                    ) VALUES (?, ?, 'open', 2, ?, NULL)
                    """,
                    ("ABC234", "a" * 64, "2026-08-10T01:00:00+00:00"),
                )
                connection.execute(
                    """
                    INSERT INTO orders (
                        group_session_id, store_profile_id, public_order_number,
                        order_access_token_hash, customer_name, total_amount, created_at
                    ) VALUES (1, NULL, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ABC234-001",
                        "b" * 64,
                        "既有訪客",
                        80,
                        "2026-08-10T01:05:00+00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            initialize_database(database_path)
            initialize_database(database_path)
            migrated = connect_database(database_path)
            try:
                group = migrated.execute(
                    "SELECT public_code, owner_user_id, archived_at FROM group_sessions"
                ).fetchone()
                order = migrated.execute(
                    "SELECT customer_name, total_amount, user_id, archived_at FROM orders"
                ).fetchone()
                foreign_key_errors = migrated.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
            finally:
                migrated.close()

        self.assertEqual(group["public_code"], "ABC234")
        self.assertIsNone(group["owner_user_id"])
        self.assertIsNone(group["archived_at"])
        self.assertEqual(order["customer_name"], "既有訪客")
        self.assertEqual(order["total_amount"], 80)
        self.assertIsNone(order["user_id"])
        self.assertIsNone(order["archived_at"])
        self.assertEqual(foreign_key_errors, [])


if __name__ == "__main__":
    unittest.main()
