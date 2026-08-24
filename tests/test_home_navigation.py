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
        self.assertIn('src="/frontend/home.js?v=', response.text)
        self.assertIn('src="/frontend/auth.js?v=', response.text)
        self.assertIn('id="auth-open-button"', response.text)

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
            "my-groups.html",
            "my-orders.html",
            "my-menus.html",
            "admin.html",
            "demo.html",
        ]
        for page_name in pages:
            html = (project_root / "frontend" / page_name).read_text(encoding="utf-8")
            with self.subTest(page=page_name):
                self.assertEqual(html.count('class="top-home-nav"'), 1)
                self.assertIn('class="top-home-brand" href="/" aria-label="席間首頁"', html)
                self.assertIn('class="top-home-brand-mark" aria-hidden="true">席</span>', html)
                self.assertIn('class="top-home-brand-name">席間<small>MENU · ORDER · TOGETHER</small>', html)
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

    def test_home_auth_keeps_guest_mode_and_uses_backend_verification(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        script = Path("frontend/auth.js").read_text(encoding="utf-8")

        self.assertIn("現在不登入也能繼續使用原本功能", html)
        self.assertIn("browserLocalPersistence", script)
        self.assertIn('fetch("/api/auth/me"', script)
        self.assertIn("firebaseUser.getIdToken()", script)
        self.assertNotIn("localStorage.setItem", script)

    def test_order_pages_load_current_account_binding_scripts(self) -> None:
        group_html = Path("frontend/group.html").read_text(encoding="utf-8")
        store_html = Path("frontend/store.html").read_text(encoding="utf-8")
        group_script = Path("frontend/group.js").read_text(encoding="utf-8")
        store_script = Path("frontend/store.js").read_text(encoding="utf-8")

        self.assertIn(
            '<script src="/frontend/group.js?v=20260819-3" defer></script>',
            group_html,
        )
        self.assertIn(
            '<script src="/frontend/store.js?v=20260824-1" defer></script>',
            store_html,
        )
        self.assertIn("window.AppAuth?.getAuthorizationHeaders", group_script)
        self.assertIn("window.AppAuth?.getAuthorizationHeaders", store_script)

    def test_home_uses_seat_brand_and_interactive_shared_flow_preview(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        script = Path("frontend/home.js").read_text(encoding="utf-8")
        style = Path("frontend/home.css").read_text(encoding="utf-8")

        self.assertIn("席間", html)
        self.assertIn("MENU · ORDER · TOGETHER", html)
        self.assertEqual(html.count('class="section-index"'), 3)
        self.assertNotIn('class="store-number"', html)
        self.assertEqual(html.count('data-flow-step="'), 4)
        self.assertEqual(html.count('data-flow-panel="'), 4)
        self.assertIn('role="tablist"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("pointerenter", script)
        self.assertIn('addEventListener("click"', script)
        self.assertIn("selectFlowStep", script)
        self.assertIn("ArrowRight", script)
        self.assertIn("requestAnimationFrame", script)
        self.assertIn("prefers-reduced-motion: reduce", style)
        self.assertIn("clamp(2.55rem, 3.8vw, 3rem)", style)
        self.assertNotIn("clamp(3.25rem, 5.2vw, 4rem)", style)
        self.assertNotIn("font-size: 5rem", style)

    def test_home_previews_explain_upload_sort_share_and_summary(self) -> None:
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        self.assertIn("拖曳菜單至此", html)
        self.assertIn("menu.jpg", html)
        self.assertIn("整理完成", html)
        self.assertIn("AB12CD", html)
        self.assertIn("12", html)
        self.assertIn("PEOPLE", html)
        self.assertIn("固定菜單如何運作", html)
        self.assertIn("店家建立菜單", html)
        self.assertIn("顧客掃碼點餐", html)
        self.assertIn("訂單自動彙整", html)
        self.assertIn("登入不是必要", html)


if __name__ == "__main__":
    unittest.main()
