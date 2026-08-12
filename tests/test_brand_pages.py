import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / "frontend"


class BrandPageTests(unittest.TestCase):
    def test_primary_inner_pages_load_the_shared_brand_layer_last(self) -> None:
        pages = [
            "upload.html",
            "group.html",
            "personal-order.html",
            "group-management.html",
            "store.html",
            "store-management.html",
            "my-groups.html",
            "my-orders.html",
            "my-menus.html",
            "admin.html",
            "demo.html",
        ]
        for page_name in pages:
            html = (FRONTEND / page_name).read_text(encoding="utf-8")
            with self.subTest(page=page_name):
                self.assertIn("/frontend/brand-pages.css", html)
                self.assertGreater(
                    html.index("/frontend/brand-pages.css"),
                    html.index("/frontend/design-system.css"),
                )

    def test_inner_brand_layer_uses_quiet_header_and_task_strength(self) -> None:
        navigation = (FRONTEND / "navigation.css").read_text(encoding="utf-8")
        style = (FRONTEND / "brand-pages.css").read_text(encoding="utf-8")

        self.assertIn(".top-home-brand-mark", navigation)
        self.assertIn(".top-home-brand-name small", navigation)
        self.assertIn(".top-home-brand:hover .top-home-brand-mark", navigation)
        self.assertNotIn("color: transparent", navigation)
        self.assertIn("background: transparent", style)
        self.assertIn(".site-header", style)
        self.assertIn(".admin-header", style)
        self.assertIn(".my-header", style)
        self.assertIn(".cart-panel", style)
        self.assertIn(".group-heading", style)
        self.assertIn("prefers-reduced-motion: reduce", style)

    def test_home_uses_one_modal_join_entry_and_no_fake_controls(self) -> None:
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        script = (FRONTEND / "home.js").read_text(encoding="utf-8")

        self.assertNotIn("AI 菜單點餐系統", html)
        self.assertNotIn("SHARE ↗", html)
        self.assertNotIn('class="orbit-dot"', html)
        self.assertNotIn('class="join-section', html)
        self.assertEqual(html.count('id="quick-group-code"'), 1)
        self.assertIn('id="quick-join-dialog"', html)
        self.assertIn("data-open-join", html)
        self.assertIn("使用 Google 登入", html)
        self.assertIn("團購點餐 · 店家掃碼點餐", html)
        self.assertIn("席間的兩種使用方式", html)
        self.assertIn('class="cta store-entry" href="/upload?mode=store"', html)
        self.assertIn("店家的菜單，<br>顧客掃碼就能點。", html)
        self.assertNotIn("常用菜單，<br>不必每次重來。", html)
        self.assertIn("showModal", script)
        self.assertIn("querySelectorAll(\"[data-open-auth]\")", script)

    def test_home_flow_uses_virtual_menu_and_real_demo_copy_feedback(self) -> None:
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        script = (FRONTEND / "home.js").read_text(encoding="utf-8")
        style = (FRONTEND / "home.css").read_text(encoding="utf-8")

        self.assertGreaterEqual(html.count("晨光早餐"), 2)
        self.assertIn("virtual-menu--incoming", html)
        self.assertIn("virtual-menu--scan", html)
        self.assertIn("data-demo-copy", html)
        self.assertIn("已複製示範連結", script)
        self.assertIn("menu-drop-in", style)
        self.assertIn("menu-scan", style)
        self.assertIn("metric-in", style)
        self.assertIn("store-journey", html)
        self.assertIn("店家先建立固定菜單，顧客掃碼點餐，系統再彙整訂單", html)
        self.assertIn("[data-parallax-root], [data-spatial-root]", script)

    def test_upload_supports_drop_replace_remove_and_real_processing_states(self) -> None:
        html = (FRONTEND / "upload.html").read_text(encoding="utf-8")
        script = (FRONTEND / "upload.js").read_text(encoding="utf-8")
        style = (FRONTEND / "brand-pages.css").read_text(encoding="utf-8")

        self.assertIn('id="file-drop-zone"', html)
        self.assertIn('id="replace-file"', html)
        self.assertIn('id="remove-file"', html)
        self.assertIn('id="processing-steps"', html)
        self.assertIn('class="upload-hero-art"', html)
        self.assertIn('id="upload-visual-step-4"', html)
        self.assertIn("FIXED MENU", script)
        self.assertIn("取得固定網址與 QR Code", script)
        self.assertIn("顧客掃碼點餐", script)
        self.assertIn("店家查看訂單彙整", script)
        self.assertIn("分享團購代碼", script)
        self.assertIn("主揪查看彙整", script)
        self.assertIn("setUploadVisual", script)
        self.assertIn('addEventListener("drop"', script)
        self.assertIn('addEventListener("pointermove"', script)
        self.assertIn('showProcessingStep("reading")', script)
        self.assertIn('showProcessingStep("organizing")', script)
        self.assertIn('showProcessingStep("done")', script)
        self.assertIn(".file-picker.is-dragover", style)


if __name__ == "__main__":
    unittest.main()
