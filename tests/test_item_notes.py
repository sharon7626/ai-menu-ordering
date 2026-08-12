import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.database import initialize_database, save_group_menu
from backend.group_orders import hash_secret_token
from backend.main import app


MENU = {
    "restaurant": {"name": "備註測試店"},
    "categories": [
        {
            "id": "category-a",
            "name": "飲料",
            "items": [
                {
                    "id": "item-a-a",
                    "name": "紅茶",
                    "description": "",
                    "price": 35,
                    "available": True,
                }
            ],
        }
    ],
}


class ItemNoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "notes.db"
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_group_note_is_trimmed_saved_and_visible(self) -> None:
        management_token = "group-management-token"
        initialize_database(self.database_path)
        save_group_menu(
            public_code="ABC234",
            management_token_hash=hash_secret_token(management_token),
            menu=MENU,
            created_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            database_path=self.database_path,
        )

        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                created = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "小美",
                        "items": [
                            {
                                "item_id": "item-a-a",
                                "quantity": 2,
                                "note": "  半糖少冰  ",
                            }
                        ],
                    },
                )
                order_token = urlsplit(created.json()["order_url"]).fragment.removeprefix(
                    "token="
                )
                personal = client.get(
                    "/api/groups/ABC234/orders/ABC234-001",
                    headers={"Authorization": f"Bearer {order_token}"},
                )
                management = client.get(
                    "/api/groups/ABC234/management",
                    headers={"Authorization": f"Bearer {management_token}"},
                )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["items"][0]["note"], "半糖少冰")
        self.assertEqual(personal.json()["items"][0]["note"], "半糖少冰")
        self.assertEqual(management.json()["orders"][0]["items"][0]["note"], "半糖少冰")
        self.assertIn("備註：半糖少冰", management.json()["text_summary"])

    def test_store_note_is_saved_and_visible_to_store(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                store = client.post(
                    "/api/stores",
                    json={
                        "restaurant_name": "便當店",
                        "categories": [
                            {
                                "name": "主餐",
                                "items": [
                                    {
                                        "name": "雞腿飯",
                                        "description": "",
                                        "price": 120,
                                    }
                                ],
                            }
                        ],
                    },
                ).json()
                management_token = urlsplit(store["management_url"]).fragment.removeprefix(
                    "token="
                )
                created = client.post(
                    f"/api/stores/{store['public_slug']}/orders",
                    json={
                        "customer_name": "小華",
                        "items": [
                            {"item_id": "item-a-a", "quantity": 1, "note": "小辣"}
                        ],
                    },
                )
                management = client.get(
                    f"/api/stores/{store['public_slug']}/management",
                    headers={"Authorization": f"Bearer {management_token}"},
                )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["items"][0]["note"], "小辣")
        self.assertEqual(management.json()["orders"][0]["items"][0]["note"], "小辣")

    def test_note_over_200_characters_is_rejected(self) -> None:
        initialize_database(self.database_path)
        save_group_menu(
            public_code="ABC234",
            management_token_hash="a" * 64,
            menu=MENU,
            created_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
            database_path=self.database_path,
        )
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.post(
                    "/api/groups/ABC234/orders",
                    json={
                        "customer_name": "小美",
                        "items": [
                            {"item_id": "item-a-a", "quantity": 1, "note": "字" * 201}
                        ],
                    },
                )
        self.assertEqual(response.status_code, 422)

    def test_existing_database_gets_empty_note_column(self) -> None:
        connection = sqlite3.connect(self.database_path)
        connection.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_name TEXT NOT NULL,
                total_amount INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                group_session_id INTEGER,
                store_profile_id INTEGER,
                public_order_number TEXT,
                order_access_token_hash TEXT
            );
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                unit_price INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                subtotal INTEGER NOT NULL
            );
            INSERT INTO orders VALUES (1, '舊顧客', 35, '2026-08-07', NULL, NULL, NULL, NULL);
            INSERT INTO order_items VALUES (1, 1, 'item-a-a', '紅茶', 35, 1, 35);
            """
        )
        connection.commit()
        connection.close()

        initialize_database(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            note = connection.execute(
                "SELECT note FROM order_items WHERE id = 1"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(note, "")

    def test_frontend_uses_actual_name_labels_and_note_fields(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_js = (project_root / "frontend" / "upload.js").read_text(encoding="utf-8")
        group_js = (project_root / "frontend" / "group.js").read_text(encoding="utf-8")
        store_js = (project_root / "frontend" / "store.js").read_text(encoding="utf-8")

        self.assertIn('labelText: "品項名稱"', upload_js)
        self.assertNotIn("品項 ${itemIndex + 1} 名稱", upload_js)
        self.assertIn("AI 會自動帶入原菜單的菜名與價格", (project_root / "frontend" / "upload.html").read_text(encoding="utf-8"))
        self.assertIn("餐點備註（選填）", group_js)
        self.assertIn("餐點備註（選填）", store_js)
        self.assertIn("noteField.hidden = nextValue === 0", group_js)
        self.assertIn("noteField.hidden = nextValue === 0", store_js)

    def test_group_review_locks_prices_and_selects_offered_items(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_js = (project_root / "frontend" / "upload.js").read_text(encoding="utf-8")

        self.assertIn("priceField.input.readOnly = true", upload_js)
        self.assertIn('includeInput.dataset.role = "include-item"', upload_js)
        self.assertIn("提供團購", upload_js)
        self.assertIn("category.items.length > 0", upload_js)

    def test_missing_restaurant_name_can_be_entered_manually(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_js = (project_root / "frontend" / "upload.js").read_text(encoding="utf-8")
        upload_html = (project_root / "frontend" / "upload.html").read_text(encoding="utf-8")

        self.assertIn("hasRecognizedRestaurantName", upload_js)
        self.assertIn('requestedMode === "group" && hasRecognizedRestaurantName', upload_js)
        self.assertIn('restaurantField.input.placeholder = "請輸入餐廳名稱"', upload_js)
        self.assertIn("菜單未辨識到店名", upload_js)
        self.assertIn("請先手動輸入名稱", upload_js)
        self.assertIn("若菜單沒有店名，可以手動輸入餐廳名稱", upload_html)
        self.assertIn("menu-variants.js?v=20260808-1", upload_html)
        self.assertIn("upload.js?v=20260811-4", upload_html)

    def test_review_has_compact_filters_and_groups_store_sizes(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_js = (project_root / "frontend" / "upload.js").read_text(encoding="utf-8")
        upload_css = (project_root / "frontend" / "upload.css").read_text(encoding="utf-8")

        self.assertIn('data-filter="keyword"', upload_js)
        self.assertIn('data-filter="category"', upload_js)
        self.assertIn('data-filter="max-price"', upload_js)
        self.assertIn("只保留篩選結果", upload_js)
        self.assertIn("applyActiveFiltersToSelection", upload_js)
        self.assertIn("MenuVariants.groupItems", upload_js)
        self.assertIn("group-variant-group", upload_js)
        self.assertIn("store-variant-group", upload_js)
        self.assertIn(".group-select-item", upload_css)
        self.assertIn(".group-variant-options", upload_css)
        self.assertIn(".store-variant-prices", upload_css)
        self.assertIn(".review-field[hidden]", upload_css)
        self.assertNotIn("主揪步驟 1／3", upload_js)

    def test_upload_preview_can_crop_images_before_recognition(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_html = (project_root / "frontend" / "upload.html").read_text(encoding="utf-8")
        upload_js = (project_root / "frontend" / "upload.js").read_text(encoding="utf-8")

        self.assertIn('id="menu-preview-canvas"', upload_html)
        self.assertIn('id="start-crop"', upload_html)
        self.assertIn('id="apply-crop"', upload_html)
        self.assertIn("croppedUploadFile ?? file", upload_js)
        self.assertIn("menu-selected-area.jpg", upload_js)
        self.assertIn("第一版裁切辨識範圍只支援 JPG 與 PNG", upload_js)

    def test_variants_share_one_ordering_row_with_separate_controls(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        helper = (project_root / "frontend" / "menu-variants.js").read_text(
            encoding="utf-8"
        )
        upload_script = (project_root / "frontend" / "upload.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("function parseVariantName", helper)
        self.assertIn("function groupItems", helper)
        self.assertIn("[^（）()]+?", helper)
        self.assertIn("MenuVariants.groupItems", upload_script)
        self.assertNotIn("function getSizeVariant", upload_script)
        for filename in ("group.js", "store.js"):
            script = (project_root / "frontend" / filename).read_text(encoding="utf-8")
            self.assertIn("createVariantMenuItem", script)
            self.assertIn("menu-variant-options", script)
            self.assertIn("createQuantityControl(item, noteField)", script)
            self.assertIn("MenuVariants.groupItems", script)
            self.assertNotIn("function getSizeVariant", script)

    def test_store_review_can_add_and_delete_categories_and_items(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_js = (project_root / "frontend" / "upload.js").read_text(encoding="utf-8")

        self.assertIn("＋ 新增菜單分類", upload_js)
        self.assertIn("＋ 新增品項", upload_js)
        self.assertIn("刪除這個分類", upload_js)
        self.assertIn("item-delete-button", upload_js)
        self.assertIn('requestedMode === "store" || Boolean(storeUpdateContext)', upload_js)


if __name__ == "__main__":
    unittest.main()
