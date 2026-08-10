import tempfile
import unittest
from pathlib import Path

from backend.database import connect_database, initialize_database


class DatabaseInitializationTests(unittest.TestCase):
    def test_initialize_and_store_order_with_multiple_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test-orders.db"

            initialize_database(database_path)
            initialize_database(database_path)

            connection = connect_database(database_path)
            try:
                table_names = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertIn("orders", table_names)
                self.assertIn("order_items", table_names)

                cursor = connection.execute(
                    """
                    INSERT INTO orders (customer_name, total_amount, created_at)
                    VALUES (?, ?, ?)
                    """,
                    ("王小明", 240, "2026-08-04T12:00:00+00:00"),
                )
                order_id = cursor.lastrowid
                connection.executemany(
                    """
                    INSERT INTO order_items (
                        order_id,
                        item_id,
                        item_name,
                        unit_price,
                        quantity,
                        subtotal
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (order_id, "braised-pork-rice", "滷肉飯", 45, 2, 90),
                        (order_id, "beef-noodle-soup", "紅燒牛肉麵", 150, 1, 150),
                    ],
                )
                connection.commit()

                saved_order = connection.execute(
                    "SELECT customer_name, total_amount FROM orders WHERE id = ?",
                    (order_id,),
                ).fetchone()
                saved_items = connection.execute(
                    """
                    SELECT item_id, quantity, subtotal
                    FROM order_items
                    WHERE order_id = ?
                    ORDER BY id
                    """,
                    (order_id,),
                ).fetchall()

                self.assertEqual(saved_order["customer_name"], "王小明")
                self.assertEqual(saved_order["total_amount"], 240)
                self.assertEqual(len(saved_items), 2)
                self.assertEqual(sum(row["subtotal"] for row in saved_items), 240)
                self.assertEqual(saved_items[0]["quantity"], 2)
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone()[0],
                    1,
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
