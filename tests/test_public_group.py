import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.database import connect_database, initialize_database, save_group_menu
from backend.group_orders import hash_secret_token
from backend.main import app


TEST_MENU = {
    "restaurant": {"name": "分享測試餐廳"},
    "categories": [
        {
            "id": "category-a",
            "name": "點心",
            "items": [
                {
                    "id": "item-a-a",
                    "name": "蘿蔔糕",
                    "description": "",
                    "price": 55,
                    "available": True,
                }
            ],
        }
    ],
}


class PublicGroupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "public-group.db"
        initialize_database(self.database_path)
        self.group_id = save_group_menu(
            public_code="ABC234",
            management_token_hash=hash_secret_token("test-management-token"),
            menu=TEST_MENU,
            created_at=datetime(2026, 8, 7, 6, 30, tzinfo=timezone.utc),
            database_path=self.database_path,
        )
        self.database_url = f"sqlite:///{self.database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_public_code_returns_only_public_menu_data(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get("/api/groups/abc234")
                page_response = client.get("/groups/ABC234")

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["public_code"], "ABC234")
        self.assertEqual(result["status"], "open")
        self.assertEqual(result["menu"]["restaurant"]["name"], "分享測試餐廳")
        self.assertNotIn("management_token_hash", response.text)
        self.assertNotIn("test-management-token", response.text)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("加入團購", page_response.text)

    def test_missing_code_has_clear_not_found_message(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get("/api/groups/ZZZ999")

        self.assertEqual(response.status_code, 404)
        self.assertIn("找不到這個團購", response.json()["detail"])

    def test_closed_group_returns_menu_with_closed_status(self) -> None:
        connection = connect_database(self.database_path)
        try:
            connection.execute(
                """
                UPDATE group_sessions
                SET status = 'closed', closed_at = ?
                WHERE id = ?
                """,
                ("2026-08-07T07:00:00+00:00", self.group_id),
            )
            connection.commit()
        finally:
            connection.close()

        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get("/api/groups/ABC234")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "closed")
        self.assertEqual(
            response.json()["menu"]["categories"][0]["items"][0]["name"],
            "蘿蔔糕",
        )


if __name__ == "__main__":
    unittest.main()
