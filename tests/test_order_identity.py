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
    "restaurant_name": "身分測試店",
    "categories": [
        {
            "name": "主餐",
            "items": [{"name": "測試餐", "description": "", "price": 80}],
        }
    ],
}


def order(**extra) -> dict:
    return {
        "customer_name": "測試者",
        "items": [{"item_id": "item-a-a", "quantity": 1, "note": ""}],
        **extra,
    }


class OrderIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "identity.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_guest_requires_valid_contact_and_management_can_identify_order(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=MENU).json()
                code = group["public_code"]
                token = urlsplit(group["management_url"]).fragment.removeprefix("token=")

                missing = client.post(f"/api/groups/{code}/orders", json=order())
                invalid = client.post(
                    f"/api/groups/{code}/orders",
                    json=order(contact_method="email", contact_value="not-an-email"),
                )
                created = client.post(
                    f"/api/groups/{code}/orders",
                    json=order(
                        contact_method="phone",
                        contact_value="0912-345-678",
                        edit_code="246810",
                    ),
                )
                management = client.get(
                    f"/api/groups/{code}/management",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(missing.status_code, 422)
        self.assertIn("手機號碼或 Email", missing.text)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(created.status_code, 201)
        managed_order = management.json()["orders"][0]
        self.assertEqual(managed_order["identity_method"], "phone")
        self.assertEqual(managed_order["identity_value"], "0912345678")

    def test_verified_google_account_needs_no_duplicate_guest_contact(self) -> None:
        verified_user = AuthenticatedFirebaseUser(
            uid="identity-user",
            email="person@example.com",
            display_name="登入者",
        )
        headers = {"Authorization": "Bearer verified-token"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=MENU).json()
                token = urlsplit(group["management_url"]).fragment.removeprefix("token=")
                with patch("backend.main.verify_firebase_id_token", return_value=verified_user):
                    created = client.post(
                        f"/api/groups/{group['public_code']}/orders",
                        json=order(),
                        headers=headers,
                    )
                management = client.get(
                    f"/api/groups/{group['public_code']}/management",
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(created.status_code, 201)
        managed_order = management.json()["orders"][0]
        self.assertEqual(managed_order["identity_method"], "google")
        self.assertEqual(managed_order["identity_value"], "person@example.com")

    def test_store_guest_email_is_visible_only_in_private_management(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                store = client.post("/api/stores", json=MENU).json()
                token = urlsplit(store["management_url"]).fragment.removeprefix("token=")
                created = client.post(
                    f"/api/stores/{store['public_slug']}/orders",
                    json=order(
                        contact_method="email",
                        contact_value="Guest@Example.COM",
                    ),
                )
                public_menu = client.get(f"/api/stores/{store['public_slug']}")
                management = client.get(
                    f"/api/stores/{store['public_slug']}/management",
                    headers={"X-Management-Token": token},
                )

        self.assertEqual(created.status_code, 201)
        self.assertNotIn("guest@example.com", public_menu.text.lower())
        self.assertEqual(management.status_code, 200, management.text)
        managed_order = management.json()["orders"][0]
        self.assertEqual(managed_order["identity_method"], "email")
        self.assertEqual(managed_order["identity_value"], "guest@example.com")


if __name__ == "__main__":
    unittest.main()
