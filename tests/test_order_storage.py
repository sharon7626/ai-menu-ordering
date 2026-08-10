import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.database import connect_database, initialize_database, save_order
from backend.schemas import AcceptedOrder, OrderItem


def make_order(second_item_id: str = "beef-noodle-soup") -> AcceptedOrder:
    return AcceptedOrder(
        customer_name="王小明",
        items=[
            OrderItem(
                item_id="braised-pork-rice",
                item_name="滷肉飯",
                unit_price=45,
                quantity=2,
                subtotal=90,
            ),
            OrderItem(
                item_id=second_item_id,
                item_name="紅燒牛肉麵",
                unit_price=150,
                quantity=1,
                subtotal=150,
            ),
        ],
        total_amount=240,
        created_at=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
    )


class OrderStorageTests(unittest.TestCase):
    def test_save_order_writes_order_and_all_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "saved-order.db"
            initialize_database(database_path)

            order_id = save_order(make_order(), database_path)

            connection = connect_database(database_path)
            try:
                saved_order = connection.execute(
                    """
                    SELECT customer_name, total_amount, created_at
                    FROM orders
                    WHERE id = ?
                    """,
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
                self.assertEqual(saved_order["created_at"], "2026-08-04T12:00:00+00:00")
                self.assertEqual(len(saved_items), 2)
                self.assertEqual(saved_items[0]["quantity"], 2)
                self.assertEqual(saved_items[1]["quantity"], 1)
                self.assertEqual(sum(item["subtotal"] for item in saved_items), 240)
            finally:
                connection.close()

    def test_item_write_failure_rolls_back_entire_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "failed-order.db"
            initialize_database(database_path)

            connection = connect_database(database_path)
            try:
                connection.execute(
                    """
                    CREATE TRIGGER reject_forced_failure
                    BEFORE INSERT ON order_items
                    WHEN NEW.item_id = 'force-write-failure'
                    BEGIN
                        SELECT RAISE(ABORT, 'forced test failure');
                    END;
                    """
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(sqlite3.IntegrityError):
                save_order(make_order("force-write-failure"), database_path)

            connection = connect_database(database_path)
            try:
                order_count = connection.execute(
                    "SELECT COUNT(*) FROM orders"
                ).fetchone()[0]
                item_count = connection.execute(
                    "SELECT COUNT(*) FROM order_items"
                ).fetchone()[0]
                self.assertEqual(order_count, 0)
                self.assertEqual(item_count, 0)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
