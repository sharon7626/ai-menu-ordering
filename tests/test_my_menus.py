import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.firebase_auth import AuthenticatedFirebaseUser
from backend.main import app


MENU = {
    "restaurant_name": "常用早餐店",
    "categories": [
        {
            "name": "早餐",
            "items": [{"name": "蛋餅", "description": "", "price": 45}],
        }
    ],
}


class MyMenusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "my-menus.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.user_a = AuthenticatedFirebaseUser("uid-a", "a@example.com", "A")
        self.user_b = AuthenticatedFirebaseUser("uid-b", "b@example.com", "B")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def verified_user(self, token: str) -> AuthenticatedFirebaseUser:
        return self.user_a if token == "token-a" else self.user_b

    def test_confirmed_menu_is_saved_and_reused_without_recognition(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        headers_b = {"Authorization": "Bearer token-b"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    first_group = client.post("/api/groups", json=MENU, headers=headers_a)
                    menus = client.get("/api/me/menus", headers=headers_a)
                    menu_id = menus.json()["menus"][0]["id"]
                    reused = client.post(
                        f"/api/me/menus/{menu_id}/groups", headers=headers_a
                    )
                    other_user = client.post(
                        f"/api/me/menus/{menu_id}/groups", headers=headers_b
                    )
                    groups = client.get("/api/me/groups", headers=headers_a)

        self.assertEqual(first_group.status_code, 201)
        self.assertEqual(menus.status_code, 200)
        self.assertEqual(menus.json()["menus"][0]["restaurant_name"], "常用早餐店")
        self.assertEqual(menus.json()["menus"][0]["item_count"], 1)
        self.assertEqual(reused.status_code, 201)
        self.assertNotEqual(reused.json()["public_code"], first_group.json()["public_code"])
        self.assertEqual(other_user.status_code, 403)
        self.assertEqual(len(groups.json()["groups"]), 2)

    def test_same_confirmed_menu_is_deduplicated_for_owner(self) -> None:
        headers = {"Authorization": "Bearer token-a"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token", return_value=self.user_a
                ):
                    client.post("/api/groups", json=MENU, headers=headers)
                    client.post("/api/groups", json=MENU, headers=headers)
                    menus = client.get("/api/me/menus", headers=headers)
        self.assertEqual(len(menus.json()["menus"]), 1)

    def test_fixed_store_menu_is_labeled_and_manageable_by_owner(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        headers_b = {"Authorization": "Bearer token-b"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    created = client.post("/api/stores", json=MENU, headers=headers_a)
                    slug = created.json()["public_slug"]
                    owner_menus = client.get("/api/me/menus", headers=headers_a)
                    other_menus = client.get("/api/me/menus", headers=headers_b)
                    owner_update = client.put(
                        f"/api/stores/{slug}/menu",
                        json={**MENU, "restaurant_name": "更新後固定菜單"},
                        headers=headers_a,
                    )
                    other_update = client.put(
                        f"/api/stores/{slug}/menu",
                        json=MENU,
                        headers=headers_b,
                    )

        self.assertEqual(created.status_code, 201)
        fixed_menu = owner_menus.json()["menus"][0]
        self.assertEqual(fixed_menu["menu_type"], "store_fixed")
        self.assertEqual(fixed_menu["public_slug"], slug)
        self.assertEqual(fixed_menu["version"], 1)
        self.assertEqual(other_menus.json()["menus"], [])
        self.assertEqual(owner_update.status_code, 200)
        self.assertEqual(owner_update.json()["version"], 2)
        self.assertEqual(other_update.status_code, 403)

    def test_legacy_store_can_be_claimed_only_with_management_token(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    created = client.post("/api/stores", json=MENU).json()
                    slug = created["public_slug"]
                    token = urlsplit(created["management_url"]).fragment.removeprefix("token=")
                    before = client.get("/api/me/menus", headers=headers_a)
                    denied = client.post(
                        f"/api/me/stores/{slug}/claim",
                        headers={**headers_a, "X-Management-Token": "wrong-token"},
                    )
                    claimed = client.post(
                        f"/api/me/stores/{slug}/claim",
                        headers={**headers_a, "X-Management-Token": token},
                    )
                    after = client.get("/api/me/menus", headers=headers_a)

        self.assertEqual(before.json()["menus"], [])
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(after.json()["menus"][0]["menu_type"], "store_fixed")

    def test_my_menus_page_is_available(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                page = client.get("/me/menus")
        self.assertEqual(page.status_code, 200)
        self.assertIn("我的菜單", page.text)
        self.assertIn("店家固定菜單", page.text)
        self.assertIn(
            '<script src="/frontend/my-menus.js?v=20260812-1" type="module"></script>',
            page.text,
        )


if __name__ == "__main__":
    unittest.main()
