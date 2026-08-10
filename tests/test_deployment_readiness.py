import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DeploymentReadinessTests(unittest.TestCase):
    def test_python_and_runtime_dependencies_are_pinned(self):
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        python_version = (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip()

        self.assertEqual(python_version, "3.12")
        self.assertIn("fastapi==", requirements)
        self.assertIn("uvicorn==", requirements)
        self.assertIn("psycopg[binary]==3.3.4", requirements)
        self.assertIn("google-genai==", requirements)

    def test_render_commands_match_real_fastapi_entrypoint(self):
        guide = (PROJECT_ROOT / "doc" / "render-deployment-guide.md").read_text(
            encoding="utf-8"
        )
        main_source = (PROJECT_ROOT / "backend" / "main.py").read_text(encoding="utf-8")

        self.assertIn("app = FastAPI", main_source)
        self.assertIn("pip install -r requirements.txt", guide)
        self.assertIn("uvicorn backend.main:app --host 0.0.0.0 --port $PORT", guide)
        self.assertIn("--proxy-headers", guide)

    def test_secrets_and_local_database_are_ignored(self):
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

        for ignored in (".env", "*.db", "__pycache__/", ".venv/", ".pytest_cache/"):
            self.assertIn(ignored, gitignore)
        self.assertIn("!.env.example", gitignore)
        self.assertIn("GEMINI_API_KEY=", example)
        self.assertIn("DATABASE_URL=sqlite:///./app.db", example)
        self.assertNotIn("postgresql://", example)

    def test_frontend_does_not_contain_ai_key_variable(self):
        frontend_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "frontend").glob("*")
            if path.is_file()
        )
        self.assertNotIn("GEMINI_API_KEY", frontend_source)


if __name__ == "__main__":
    unittest.main()
