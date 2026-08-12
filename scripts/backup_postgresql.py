"""將正式 PostgreSQL 匯出成 Repository 外的可驗證 ZIP 備份。

連線字串只從 DATABASE_URL 環境變數讀取。本工具不會顯示或保存連線字串，
也不會修改資料庫；ZIP 內含顧客與訂單資料，必須存放在安全的位置。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORE_TABLES = {
    "group_sessions",
    "group_menus",
    "store_profiles",
    "store_menus",
    "orders",
    "order_items",
}


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_output_directory(output_directory: Path) -> Path:
    """拒絕把含個資的正式備份寫入 Repository。"""
    resolved = output_directory.expanduser().resolve()
    if _is_inside(resolved, PROJECT_ROOT):
        raise ValueError("備份位置不可位於 ai-menu-ordering Repository 內")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _get_public_tables(connection: Any) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        return [row[0] for row in cursor.fetchall()]


def _get_columns(connection: Any, table_name: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        return [
            {
                "name": row[0],
                "data_type": row[1],
                "nullable": row[2] == "YES",
                "default": row[3],
                "position": row[4],
            }
            for row in cursor.fetchall()
        ]


def _get_row_count(connection: Any, table_name: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name))
        )
        row = cursor.fetchone()
        return int(row[0])


def _write_table_csv(
    archive: zipfile.ZipFile, connection: Any, table_name: str
) -> None:
    query = sql.SQL(
        "COPY {} TO STDOUT WITH (FORMAT CSV, HEADER TRUE, NULL '__XIJIAN_NULL__')"
    ).format(sql.Identifier(table_name))
    with archive.open(f"tables/{table_name}.csv", "w") as output_file:
        with connection.cursor() as cursor:
            with cursor.copy(query) as copy:
                for chunk in copy:
                    output_file.write(bytes(chunk))


def verify_archive(archive_path: Path) -> dict[str, Any]:
    """確認 ZIP 可讀且每張表的 CSV 列數符合 manifest。"""
    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        table_entries = manifest.get("tables")
        if not isinstance(table_entries, list) or not table_entries:
            raise ValueError("備份 manifest 沒有資料表資訊")

        for table in table_entries:
            table_name = table["name"]
            expected_count = int(table["row_count"])
            with archive.open(f"tables/{table_name}.csv", "r") as raw_file:
                text_file = io.TextIOWrapper(raw_file, encoding="utf-8", newline="")
                reader = csv.reader(text_file)
                header = next(reader, None)
                if header is None:
                    raise ValueError(f"{table_name} CSV 缺少標題列")
                actual_count = sum(1 for _ in reader)
            if actual_count != expected_count:
                raise ValueError(
                    f"{table_name} 筆數不一致：預期 {expected_count}，實際 {actual_count}"
                )
    return manifest


def create_backup(database_url: str, output_directory: Path) -> Path:
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("DATABASE_URL 必須是 PostgreSQL 連線網址")

    output_directory = validate_output_directory(output_directory)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_path = output_directory / f"ai-menu-ordering-postgresql-{timestamp}.zip"
    partial_path = final_path.with_suffix(".zip.partial")

    try:
        with psycopg.connect(database_url) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            tables = _get_public_tables(connection)
            missing_core_tables = sorted(CORE_TABLES.difference(tables))
            if missing_core_tables:
                raise RuntimeError(
                    "正式資料庫缺少核心資料表：" + ", ".join(missing_core_tables)
                )

            manifest_tables = []
            with zipfile.ZipFile(
                partial_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for table_name in tables:
                    row_count = _get_row_count(connection, table_name)
                    manifest_tables.append(
                        {
                            "name": table_name,
                            "row_count": row_count,
                            "columns": _get_columns(connection, table_name),
                        }
                    )
                    _write_table_csv(archive, connection, table_name)

                manifest = {
                    "format": "ai-menu-ordering-postgresql-csv-v1",
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "null_marker": "__XIJIAN_NULL__",
                    "tables": manifest_tables,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )

        verify_archive(partial_path)
        partial_path.replace(final_path)
        return final_path
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="安全匯出 ai-menu-ordering 正式 PostgreSQL 資料"
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Repository 外的備份資料夾",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("錯誤：目前程序沒有設定 DATABASE_URL。", file=sys.stderr)
        return 2

    try:
        archive_path = create_backup(database_url, args.output)
        manifest = verify_archive(archive_path)
    except Exception as error:
        print(f"備份失敗：{type(error).__name__}", file=sys.stderr)
        return 1

    total_rows = sum(int(table["row_count"]) for table in manifest["tables"])
    print("備份完成並通過 ZIP 完整性與資料筆數驗證。")
    print(f"檔案：{archive_path}")
    print(f"資料表：{len(manifest['tables'])}，資料列：{total_rows}")
    print("此檔包含顧客與訂單資料，請勿上傳 GitHub 或公開分享。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
