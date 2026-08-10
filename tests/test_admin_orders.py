import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.database import get_orders_with_items, initialize_database, save_order
from backend.schemas import AcceptedOrder, OrderItem


def make_admin_test_order(
    customer_name: str,
    created_at: datetime,
    items: list[OrderItem],
) -> AcceptedOrder:
    return AcceptedOrder(
        customer_name=customer_name,
        items=items,
        total_amount=sum(item.subtotal for item in items),
        created_at=created_at,
    )


class AdminOrderQueryTests(unittest.TestCase):
    def test_empty_database_returns_empty_order_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "empty-admin-orders.db"
            initialize_database(database_path)

            self.assertEqual(get_orders_with_items(database_path), [])

    def test_query_returns_multiple_orders_with_complete_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "admin-orders.db"
            initialize_database(database_path)

            older_order = make_admin_test_order(
                customer_name="王小明",
                created_at=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
                items=[
                    OrderItem(
                        item_id="braised-pork-rice",
                        item_name="滷肉飯",
                        unit_price=45,
                        quantity=2,
                        subtotal=90,
                    ),
                    OrderItem(
                        item_id="beef-noodle-soup",
                        item_name="紅燒牛肉麵",
                        unit_price=150,
                        quantity=1,
                        subtotal=150,
                    ),
                ],
            )
            newer_order = make_admin_test_order(
                customer_name="陳小華",
                created_at=datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
                items=[
                    OrderItem(
                        item_id="sesame-noodles",
                        item_name="麻醬麵",
                        unit_price=65,
                        quantity=3,
                        subtotal=195,
                    )
                ],
            )
            older_order_id = save_order(older_order, database_path)
            newer_order_id = save_order(newer_order, database_path)

            orders = get_orders_with_items(database_path)

            self.assertEqual(len(orders), 2)
            self.assertEqual(
                [order["order_id"] for order in orders],
                [newer_order_id, older_order_id],
            )
            self.assertEqual(orders[0]["customer_name"], "陳小華")
            self.assertEqual(orders[0]["total_amount"], 195)
            self.assertEqual(len(orders[0]["items"]), 1)
            self.assertEqual(orders[0]["items"][0]["quantity"], 3)
            self.assertEqual(orders[1]["customer_name"], "王小明")
            self.assertEqual(orders[1]["total_amount"], 240)
            self.assertEqual(len(orders[1]["items"]), 2)
            self.assertEqual(
                [item["quantity"] for item in orders[1]["items"]],
                [2, 1],
            )


if __name__ == "__main__":
    unittest.main()
