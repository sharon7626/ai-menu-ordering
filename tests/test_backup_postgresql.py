import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.backup_postgresql import PROJECT_ROOT, validate_output_directory, verify_archive


class PostgreSQLBackupTests(unittest.TestCase):
    def test_repository_is_rejected_as_backup_destination(self):
        with self.assertRaisesRegex(ValueError, "不可位於"):
            validate_output_directory(PROJECT_ROOT / "backups")

    def test_verified_archive_checks_csv_row_counts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "backup.zip"
            manifest = {
                "format": "ai-menu-ordering-postgresql-csv-v1",
                "tables": [
                    {
                        "name": "orders",
                        "row_count": 2,
                        "columns": [{"name": "id"}],
                    }
                ],
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("tables/orders.csv", "id,name\r\n1,甲\r\n2,乙\r\n")

            verified = verify_archive(archive_path)

        self.assertEqual(verified["tables"][0]["row_count"], 2)

    def test_invalid_row_count_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "backup.zip"
            manifest = {
                "format": "ai-menu-ordering-postgresql-csv-v1",
                "tables": [{"name": "orders", "row_count": 2, "columns": []}],
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("tables/orders.csv", "id\r\n1\r\n")

            with self.assertRaisesRegex(ValueError, "筆數不一致"):
                verify_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
