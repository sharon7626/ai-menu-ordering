import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import connect_database
from backend.main import app


VALID_CONFIRMATION = {
    "restaurant_name": "任意測試餐廳",
    "categories": [
        {
            "name": "今日便當",
            "items": [
                {"name": "雞腿便當", "description": "附三樣菜", "price": 120},
                {"name": "蔬食便當", "description": "", "price": 100},
            ],
        },
        {
            "name": "飲料",
            "items": [
                {"name": "無糖綠茶", "description": "", "price": 30},
            ],
        },
    ],
}


class GroupCreationTests(unittest.TestCase):
    def test_confirmed_menu_creates_group_and_only_stores_token_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "created-group.db"
            menu_path = Path("data/menu.json")
            menu_before = menu_path.read_bytes()
            database_url = f"sqlite:///{database_path.as_posix()}"

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                with TestClient(app) as client:
                    response = client.post("/api/groups", json=VALID_CONFIRMATION)

            self.assertEqual(response.status_code, 201)
            result = response.json()
            self.assertRegex(result["public_code"], r"^[A-HJ-NP-Z2-9]{6}$")
            self.assertEqual(result["restaurant_name"], "任意測試餐廳")
            self.assertEqual(result["category_count"], 2)
            self.assertEqual(result["item_count"], 3)
            self.assertEqual(
                result["participant_url"],
                f"/groups/{result['public_code']}",
            )

            token_match = re.search(r"#token=(.+)$", result["management_url"])
            self.assertIsNotNone(token_match)
            raw_token = token_match.group(1)

            connection = connect_database(database_path)
            try:
                saved_group = connection.execute(
                    """
                    SELECT id, public_code, management_token_hash, status
                    FROM group_sessions
                    """
                ).fetchone()
                saved_menu = connection.execute(
                    "SELECT menu_json FROM group_menus WHERE group_session_id = ?",
                    (saved_group["id"],),
                ).fetchone()
            finally:
                connection.close()

            self.assertEqual(saved_group["public_code"], result["public_code"])
            self.assertEqual(saved_group["status"], "open")
            self.assertNotIn(raw_token, str(dict(saved_group)))
            self.assertEqual(
                saved_group["management_token_hash"],
                hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            )

            menu = json.loads(saved_menu["menu_json"])
            self.assertEqual(menu["restaurant"]["name"], "任意測試餐廳")
            self.assertEqual(menu["categories"][0]["id"], "category-a")
            self.assertEqual(menu["categories"][0]["items"][0]["id"], "item-a-a")
            self.assertEqual(menu["categories"][1]["name"], "飲料")
            self.assertEqual(menu["categories"][1]["items"][0]["price"], 30)
            self.assertTrue(menu["categories"][1]["items"][0]["available"])
            self.assertEqual(menu_path.read_bytes(), menu_before)

    def test_invalid_confirmation_does_not_create_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "invalid-group.db"
            database_url = f"sqlite:///{database_path.as_posix()}"

            with patch.dict(os.environ, {"DATABASE_URL": database_url}):
                with TestClient(app) as client:
                    response = client.post(
                        "/api/groups",
                        json={"restaurant_name": "", "categories": []},
                    )

            self.assertEqual(response.status_code, 422)
            connection = connect_database(database_path)
            try:
                count = connection.execute(
                    "SELECT COUNT(*) FROM group_sessions"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
