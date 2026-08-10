import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class HomeNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "home.db"
        self.database_url = f"sqlite:///{database_path.as_posix()}"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_home_offers_both_menu_upload_modes_and_group_join(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("我是主揪／統籌", response.text)
        self.assertIn("我是一起點餐的人", response.text)
        self.assertIn("店家固定菜單", response.text)
        self.assertIn('href="/upload?mode=group"', response.text)
        self.assertIn('href="/upload?mode=store"', response.text)
        self.assertIn('id="quick-group-code"', response.text)
        self.assertIn('src="/frontend/home.js"', response.text)

    def test_home_explains_organizer_then_participant_flow(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        script = Path("frontend/home.js").read_text(encoding="utf-8")

        self.assertIn("主揪上傳菜單", html)
        self.assertIn("AI 擷取菜名與價格", html)
        self.assertIn("分享連結或代碼", html)
        self.assertIn("大家各自點餐", html)
        self.assertIn("主揪查看統計", html)
        self.assertIn("window.location.assign(`/groups/${code}`)", script)

    def test_old_fixed_menu_remains_available_only_as_demo(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                home = client.get("/")
                demo = client.get("/demo")

        self.assertNotIn('id="menu-content"', home.text)
        self.assertNotIn('href="/demo"', home.text)
        self.assertEqual(demo.status_code, 200)
        self.assertIn('id="menu-content"', demo.text)
        self.assertIn("固定的示範菜單資料", demo.text)

    def test_subpages_have_one_home_button_at_the_top(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        pages = [
            "upload.html",
            "group.html",
            "group-management.html",
            "personal-order.html",
            "store.html",
            "store-management.html",
            "admin.html",
            "demo.html",
        ]
        for page_name in pages:
            html = (project_root / "frontend" / page_name).read_text(encoding="utf-8")
            with self.subTest(page=page_name):
                self.assertEqual(html.count('class="top-home-nav"'), 1)
                self.assertIn('<a href="/">首頁</a>', html)
                self.assertIn('/frontend/navigation.css', html)

        home = (project_root / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="top-actions"', home)

    def test_upload_script_separates_group_and_store_mode_controls(self) -> None:
        script = Path("frontend/upload.js").read_text(encoding="utf-8")

        self.assertIn('requestedMode === "group"', script)
        self.assertIn('requestedMode === "store"', script)
        self.assertIn("storeButton.hidden = true", script)
        self.assertIn("confirmButton.hidden = true", script)

    def test_short_upload_url_preserves_selected_mode(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": self.database_url}):
            with TestClient(app) as client:
                group = client.get("/upload?mode=group", follow_redirects=False)
                store = client.get("/upload?mode=store", follow_redirects=False)

        self.assertEqual(group.headers["location"], "/frontend/upload.html?mode=group")
        self.assertEqual(store.headers["location"], "/frontend/upload.html?mode=store")


if __name__ == "__main__":
    unittest.main()
