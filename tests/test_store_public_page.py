import os
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.store_qr import build_store_qr_svg


def store_confirmation(restaurant_name: str, item_name: str) -> dict:
    return {
        "restaurant_name": restaurant_name,
        "categories": [
            {
                "name": "本店餐點",
                "items": [
                    {"name": item_name, "description": "", "price": 80},
                ],
            }
        ],
    }


class StorePublicPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "store-public.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_two_fixed_urls_return_only_their_own_current_menu(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                first = client.post(
                    "/api/stores",
                    json=store_confirmation("第一家店", "第一家餐點"),
                ).json()
                second = client.post(
                    "/api/stores",
                    json=store_confirmation("第二家店", "第二家餐點"),
                ).json()

                first_menu = client.get(f"/api/stores/{first['public_slug']}")
                second_menu = client.get(f"/api/stores/{second['public_slug']}")
                first_page = client.get(first["public_url"])

        self.assertEqual(first_menu.status_code, 200)
        self.assertEqual(second_menu.status_code, 200)
        self.assertEqual(first_menu.json()["menu"]["restaurant"]["name"], "第一家店")
        self.assertEqual(second_menu.json()["menu"]["restaurant"]["name"], "第二家店")
        self.assertNotIn("第二家餐點", first_menu.text)
        self.assertNotIn("第一家餐點", second_menu.text)
        self.assertNotIn("management", first_menu.text.lower())
        self.assertNotIn("token", first_menu.text.lower())
        self.assertEqual(first_page.status_code, 200)
        self.assertIn("店家線上菜單", first_page.text)
        self.assertNotIn("token", first_page.text.lower())

    def test_qr_endpoint_encodes_only_complete_public_url(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                created = client.post(
                    "/api/stores",
                    json=store_confirmation("QR 測試店", "測試餐點"),
                ).json()
                slug = created["public_slug"]
                expected_target = f"http://testserver/stores/{slug}"

                with patch(
                    "backend.main.build_store_qr_svg",
                    return_value=b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                ) as qr_builder:
                    response = client.get(f"/api/stores/{slug}/qr.svg")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("image/svg+xml"))
        qr_builder.assert_called_once_with(expected_target)
        self.assertNotIn("token", expected_target.lower())
        self.assertNotIn("#", expected_target)
        self.assertNotIn("?", expected_target)

    def test_real_svg_is_valid_and_rejects_non_public_url_parts(self) -> None:
        svg = build_store_qr_svg("http://127.0.0.1:8000/stores/abcdefgh")
        root = ElementTree.fromstring(svg)

        self.assertTrue(root.tag.endswith("svg"))
        self.assertGreater(len(svg), 1000)
        self.assertNotIn(b"token", svg.lower())
        with self.assertRaises(ValueError):
            build_store_qr_svg(
                "http://127.0.0.1:8000/stores/abcdefgh#token=not-allowed"
            )
        with self.assertRaises(ValueError):
            build_store_qr_svg(
                "http://127.0.0.1:8000/stores/abcdefgh?token=not-allowed"
            )

    def test_unknown_store_has_no_public_menu_or_qr(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                menu_response = client.get("/api/stores/abcdefgh")
                qr_response = client.get("/api/stores/abcdefgh/qr.svg")

        self.assertEqual(menu_response.status_code, 404)
        self.assertEqual(qr_response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
