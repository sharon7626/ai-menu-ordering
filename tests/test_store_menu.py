import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import connect_database
from backend.main import app


FIRST_MENU = {
    "restaurant_name": "固定菜單測試店",
    "categories": [
        {
            "name": "主餐",
            "items": [
                {"name": "舊版雞腿飯", "description": "", "price": 100},
            ],
        }
    ],
}

UPDATED_MENU = {
    "restaurant_name": "固定菜單測試店",
    "categories": [
        {
            "name": "新版主餐",
            "items": [
                {"name": "新版雞腿飯", "description": "加量", "price": 120},
            ],
        },
        {
            "name": "飲料",
            "items": [
                {"name": "紅茶", "description": "", "price": 30},
            ],
        },
    ],
}


class StoreMenuTests(unittest.TestCase):
    def test_store_update_page_supports_current_menu_and_new_upload(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        upload_html = (project_root / "frontend" / "upload.html").read_text(
            encoding="utf-8"
        )
        upload_js = (project_root / "frontend" / "upload.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('id="edit-current-menu"', upload_html)
        self.assertIn('id="upload-new-menu"', upload_html)
        self.assertIn("直接修改目前菜單", upload_html)
        self.assertIn("上傳全新菜單", upload_html)
        self.assertIn("function publicMenuToRecognition", upload_js)
        self.assertIn("function loadCurrentStoreMenu", upload_js)
        self.assertIn(
            "fetch(`/api/stores/${encodeURIComponent(storeUpdateContext.publicSlug)}`)",
            upload_js,
        )
        self.assertIn('renderRecognition(cloneRecognition(currentStoreRecognition), "current")', upload_js)
        self.assertIn('renderRecognition(result.recognition, "upload")', upload_js)

    def test_create_update_public_menu_and_preserve_old_order_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "store-menu.db"
            database_url = f"sqlite:///{database_path.as_posix()}"
            demo_menu_path = Path("data/menu.json")
            demo_before = demo_menu_path.read_bytes()

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                with TestClient(app) as client:
                    create_response = client.post("/api/stores", json=FIRST_MENU)
                    self.assertEqual(create_response.status_code, 201)
                    created = create_response.json()
                    slug = created["public_slug"]
                    self.assertRegex(slug, r"^[a-z]{8}$")
                    self.assertEqual(created["public_url"], f"/stores/{slug}")
                    token = created["management_url"].split("#token=", 1)[1]
                    self.assertEqual(
                        created["menu_update_url"],
                        f"/stores/{slug}/menu-update#token={token}",
                    )

                    first_public = client.get(f"/api/stores/{slug}")
                    self.assertEqual(first_public.status_code, 200)
                    self.assertEqual(first_public.json()["version"], 1)
                    self.assertEqual(
                        first_public.json()["menu"]["categories"][0]["items"][0]["price"],
                        100,
                    )
                    self.assertNotIn("token", first_public.text.lower())

                    connection = connect_database(database_path)
                    try:
                        store = connection.execute(
                            """
                            SELECT id, management_token_hash
                            FROM store_profiles
                            WHERE public_slug = ?
                            """,
                            (slug,),
                        ).fetchone()
                        order_cursor = connection.execute(
                            """
                            INSERT INTO orders (
                                store_profile_id,
                                public_order_number,
                                order_access_token_hash,
                                customer_name,
                                total_amount,
                                created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                store["id"],
                                f"S-{slug[:6].upper()}-001",
                                "c" * 64,
                                "舊訂單顧客",
                                100,
                                "2026-08-07T08:00:00+00:00",
                            ),
                        )
                        connection.execute(
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
                            (
                                order_cursor.lastrowid,
                                "item-a-a",
                                "舊版雞腿飯",
                                100,
                                1,
                                100,
                            ),
                        )
                        connection.commit()
                    finally:
                        connection.close()

                    update_response = client.put(
                        f"/api/stores/{slug}/menu",
                        headers={"Authorization": f"Bearer {token}"},
                        json=UPDATED_MENU,
                    )
                    self.assertEqual(update_response.status_code, 200)
                    updated = update_response.json()
                    self.assertEqual(updated["public_url"], created["public_url"])
                    self.assertEqual(updated["version"], 2)

                    second_public = client.get(f"/api/stores/{slug}")
                    self.assertEqual(second_public.json()["version"], 2)
                    self.assertEqual(
                        second_public.json()["menu"]["categories"][0]["items"][0]["name"],
                        "新版雞腿飯",
                    )
                    self.assertEqual(
                        second_public.json()["menu"]["categories"][0]["items"][0]["price"],
                        120,
                    )

            connection = connect_database(database_path)
            try:
                old_item = connection.execute(
                    """
                    SELECT item_name, unit_price, subtotal
                    FROM order_items
                    WHERE item_name = '舊版雞腿飯'
                    """
                ).fetchone()
                stored_hash = connection.execute(
                    "SELECT management_token_hash FROM store_profiles"
                ).fetchone()["management_token_hash"]
            finally:
                connection.close()

            self.assertEqual(old_item["item_name"], "舊版雞腿飯")
            self.assertEqual(old_item["unit_price"], 100)
            self.assertEqual(old_item["subtotal"], 100)
            self.assertEqual(
                stored_hash,
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
            )
            self.assertNotIn(token, stored_hash)
            self.assertEqual(demo_menu_path.read_bytes(), demo_before)

    def test_wrong_management_token_cannot_update_store_menu(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "store-denied.db"
            database_url = f"sqlite:///{database_path.as_posix()}"

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                with TestClient(app) as client:
                    created = client.post("/api/stores", json=FIRST_MENU).json()
                    slug = created["public_slug"]
                    denied = client.put(
                        f"/api/stores/{slug}/menu",
                        headers={"Authorization": "Bearer wrong-token"},
                        json=UPDATED_MENU,
                    )
                    current = client.get(f"/api/stores/{slug}")

            self.assertEqual(denied.status_code, 403)
            self.assertEqual(current.json()["version"], 1)
            self.assertEqual(
                current.json()["menu"]["categories"][0]["items"][0]["name"],
                "舊版雞腿飯",
            )


if __name__ == "__main__":
    unittest.main()
