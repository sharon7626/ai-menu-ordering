import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DesignSystemTests(unittest.TestCase):
    def test_all_pages_load_the_shared_design_system_before_page_styles(self) -> None:
        for page in (PROJECT_ROOT / "frontend").glob("*.html"):
            html = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertIn("/frontend/design-system.css", html)
                self.assertLess(
                    html.index("/frontend/design-system.css"),
                    html.index("</head>"),
                )

    def test_tokens_components_focus_and_reduced_motion_are_defined(self) -> None:
        css = (PROJECT_ROOT / "frontend" / "design-system.css").read_text(
            encoding="utf-8"
        )
        for token in (
            "--color-bg",
            "--color-surface",
            "--color-accent",
            "--color-warm",
            "--text-display",
            "--space-8",
            "--radius-lg",
            "--motion-normal",
            "--ease-standard",
        ):
            self.assertIn(token, css)
        for component in (
            ".ds-button",
            ".ds-field",
            ".ds-card",
            ".ds-badge",
            ".ds-nav",
            ".ds-modal",
            ".ds-toast",
            ".ds-loading",
            ".ds-empty",
        ):
            self.assertIn(component, css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion: reduce", css)


if __name__ == "__main__":
    unittest.main()
