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
    "restaurant_name": "Claim 測試",
    "categories": [
        {
            "name": "餐點",
            "items": [{"name": "測試餐", "description": "", "price": 60}],
        }
    ],
}
ORDER = {
    "customer_name": "訪客",
    "contact_method": "email",
    "contact_value": "guest@example.com",
    "items": [{"item_id": "item-a-a", "quantity": 1, "note": ""}],
}


class AccountClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "claim.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"
        self.user_a = AuthenticatedFirebaseUser("uid-a", "a@example.com", "A")
        self.user_b = AuthenticatedFirebaseUser("uid-b", "b@example.com", "B")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def verified_user(self, token: str) -> AuthenticatedFirebaseUser:
        return self.user_a if token == "token-a" else self.user_b

    def test_valid_private_tokens_claim_guest_group_and_both_order_modes(self) -> None:
        auth_a = {"Authorization": "Bearer token-a"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=MENU).json()
                store = client.post("/api/stores", json=MENU).json()
                group_order = client.post(
                    f"/api/groups/{group['public_code']}/orders",
                    json={**ORDER, "edit_code": "246810"},
                ).json()
                store_order = client.post(
                    f"/api/stores/{store['public_slug']}/orders",
                    json={**ORDER, "edit_code": "135790"},
                ).json()
                management_token = urlsplit(group["management_url"]).fragment.removeprefix("token=")
                group_order_token = urlsplit(group_order["order_url"]).fragment.removeprefix("token=")
                store_order_token = urlsplit(store_order["order_url"]).fragment.removeprefix("token=")

                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    claim_group = client.post(
                        f"/api/me/groups/{group['public_code']}/claim",
                        headers={**auth_a, "X-Management-Token": management_token},
                    )
                    claim_group_again = client.post(
                        f"/api/me/groups/{group['public_code']}/claim",
                        headers={**auth_a, "X-Management-Token": management_token},
                    )
                    claim_group_order = client.post(
                        f"/api/me/group-orders/{group['public_code']}/{group_order['public_order_number']}/claim",
                        headers={**auth_a, "X-Order-Token": group_order_token},
                    )
                    claim_store_order = client.post(
                        f"/api/me/store-orders/{store['public_slug']}/{store_order['public_order_number']}/claim",
                        headers={**auth_a, "X-Order-Token": store_order_token},
                    )
                    my_groups = client.get("/api/me/groups", headers=auth_a)
                    my_orders = client.get("/api/me/orders", headers=auth_a)

        for response in (claim_group, claim_group_again, claim_group_order, claim_store_order):
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(my_groups.json()["groups"]), 1)
        self.assertEqual(len(my_orders.json()["orders"]), 2)

    def test_wrong_missing_or_other_users_claim_is_rejected_without_details(self) -> None:
        auth_a = {"Authorization": "Bearer token-a"}
        auth_b = {"Authorization": "Bearer token-b"}
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}, clear=True):
            with TestClient(app) as client:
                group = client.post("/api/groups", json=MENU).json()
                management_token = urlsplit(group["management_url"]).fragment.removeprefix("token=")
                with patch(
                    "backend.main.verify_firebase_id_token",
                    side_effect=self.verified_user,
                ):
                    missing = client.post(
                        f"/api/me/groups/{group['public_code']}/claim", headers=auth_a
                    )
                    wrong = client.post(
                        f"/api/me/groups/{group['public_code']}/claim",
                        headers={**auth_a, "X-Management-Token": "wrong-token"},
                    )
                    valid = client.post(
                        f"/api/me/groups/{group['public_code']}/claim",
                        headers={**auth_a, "X-Management-Token": management_token},
                    )
                    other = client.post(
                        f"/api/me/groups/{group['public_code']}/claim",
                        headers={**auth_b, "X-Management-Token": management_token},
                    )

        self.assertEqual(valid.status_code, 200)
        for response in (missing, wrong, other):
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("uid", response.text.lower())
            self.assertNotIn("owner", response.text.lower())
            self.assertNotIn("wrong-token", response.text)


if __name__ == "__main__":
    unittest.main()
