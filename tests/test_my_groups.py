import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.firebase_auth import AuthenticatedFirebaseUser
from backend.main import app


def confirmation(name: str) -> dict:
    return {
        "restaurant_name": name,
        "categories": [
            {
                "name": "餐點",
                "items": [{"name": "測試餐", "description": "", "price": 90}],
            }
        ],
    }


class MyGroupsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "my-groups.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.user_a = AuthenticatedFirebaseUser("uid-a", "a@example.com", "使用者 A")
        self.user_b = AuthenticatedFirebaseUser("uid-b", "b@example.com", "使用者 B")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def verified_user(self, token: str) -> AuthenticatedFirebaseUser:
        return self.user_a if token == "token-a" else self.user_b

    def test_my_groups_are_isolated_and_owner_can_manage_without_original_token(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        headers_b = {"Authorization": "Bearer token-b"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    group_a = client.post(
                        "/api/groups", json=confirmation("A 的團購"), headers=headers_a
                    ).json()
                    group_b = client.post(
                        "/api/groups", json=confirmation("B 的團購"), headers=headers_b
                    ).json()
                    mine = client.get("/api/me/groups", headers=headers_a)
                    archived = client.post(
                        f"/api/me/groups/{group_a['public_code']}/archive",
                        headers=headers_a,
                    )
                    active_after_archive = client.get(
                        "/api/me/groups", headers=headers_a
                    )
                    archived_list = client.get(
                        "/api/me/groups?archived=true", headers=headers_a
                    )
                    other_archive = client.post(
                        f"/api/me/groups/{group_a['public_code']}/archive",
                        headers=headers_b,
                    )
                    restored = client.post(
                        f"/api/me/groups/{group_a['public_code']}/restore",
                        headers=headers_a,
                    )
                    active_after_restore = client.get(
                        "/api/me/groups", headers=headers_a
                    )
                    qr = client.get(f"/api/groups/{group_a['public_code']}/qr.svg")
                    own_management = client.get(
                        f"/api/me/groups/{group_a['public_code']}/management",
                        headers=headers_a,
                    )
                    other_management = client.get(
                        f"/api/me/groups/{group_b['public_code']}/management",
                        headers=headers_a,
                    )
                    closed = client.post(
                        f"/api/me/groups/{group_a['public_code']}/close",
                        headers=headers_a,
                    )

        self.assertEqual(mine.status_code, 200)
        self.assertEqual([group["restaurant_name"] for group in mine.json()["groups"]], ["A 的團購"])
        self.assertNotIn("token", mine.text.lower())
        self.assertEqual(
            mine.json()["groups"][0]["public_url"],
            f"/groups/{group_a['public_code']}",
        )
        self.assertEqual(
            mine.json()["groups"][0]["archive_api_url"],
            f"/api/me/groups/{group_a['public_code']}",
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(active_after_archive.json()["groups"], [])
        self.assertEqual(
            [group["public_code"] for group in archived_list.json()["groups"]],
            [group_a["public_code"]],
        )
        self.assertEqual(other_archive.status_code, 403)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(
            [group["public_code"] for group in active_after_restore.json()["groups"]],
            [group_a["public_code"]],
        )
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.headers["content-type"], "image/svg+xml")
        self.assertNotIn("token", qr.text.lower())
        self.assertEqual(own_management.status_code, 200)
        self.assertEqual(other_management.status_code, 403)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["status"], "closed")

    def test_existing_management_token_still_works(self) -> None:
        headers_a = {"Authorization": "Bearer token-a"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                with patch(
                    "backend.main.verify_firebase_id_token",
                    return_value=self.user_a,
                ):
                    created = client.post(
                        "/api/groups", json=confirmation("保留 Token"), headers=headers_a
                    ).json()
                token = urlsplit(created["management_url"]).fragment.removeprefix("token=")
                response = client.get(
                    f"/api/groups/{created['public_code']}/management",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["restaurant_name"], "保留 Token")

    def test_my_groups_page_is_available_without_exposing_data_in_html(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                page = client.get("/me/groups")

        self.assertEqual(page.status_code, 200)
        self.assertIn("我的團購", page.text)
        self.assertIn(
            '<script src="/frontend/my-groups.js?v=20260811-4" type="module"></script>',
            page.text,
        )
        self.assertNotIn("firebase_uid", page.text)

        script = Path("frontend/my-groups.js").read_text(encoding="utf-8")
        self.assertIn("分享連結與 QR Code", script)
        self.assertIn("複製參與連結", script)
        self.assertIn("封存團購", script)
        self.assertIn("恢復團購", script)


if __name__ == "__main__":
    unittest.main()
