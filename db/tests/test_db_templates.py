import re
import unittest
from pathlib import Path


DB_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_SQL_PATH = DB_DIR / "create_db_template.sql"
AUTH_SQL_PATH = DB_DIR / "create_auth_db.sql"


def _read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _table_block(sql_text: str, table_name: str) -> str:
    pattern = re.compile(
        rf"CREATE TABLE(?: IF NOT EXISTS)?\s+{re.escape(table_name)}\s*\((.*?)\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(sql_text)
    if not match:
        raise AssertionError(f"Missing CREATE TABLE definition for {table_name}")
    return match.group(1)


def _varchar_length(sql_text: str, table_name: str, column_name: str) -> int:
    block = _table_block(sql_text, table_name)
    pattern = re.compile(rf"\b{re.escape(column_name)}\s+varchar\((\d+)\)", re.IGNORECASE)
    match = pattern.search(block)
    if not match:
        raise AssertionError(f"Missing varchar column {table_name}.{column_name}")
    return int(match.group(1))


class CreateDbTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template_sql = _read_sql(TEMPLATE_SQL_PATH)
        cls.auth_sql = _read_sql(AUTH_SQL_PATH)

    def test_template_creates_expected_database_and_postgis_extension(self) -> None:
        self.assertIn("CREATE DATABASE terrain_db_template", self.template_sql)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS postgis;", self.template_sql)

    def test_template_declares_core_tables(self) -> None:
        expected_tables = [
            "gloss_personalia",
            "tab_geopts",
            "tab_polygons",
            "tab_sj",
            "tab_photos",
            "tab_sketches",
            "tab_drawings",
            "tab_photograms",
            "tab_finds",
            "tab_samples",
        ]

        for table_name in expected_tables:
            with self.subTest(table=table_name):
                pattern = re.compile(
                    rf"CREATE TABLE(?: IF NOT EXISTS)?\s+{re.escape(table_name)}\s*\(",
                    re.IGNORECASE,
                )
                self.assertRegex(self.template_sql, pattern)

    def test_join_table_identifier_lengths_match_parent_keys(self) -> None:
        expected_matches = [
            ("tab_photos", "id_photo", "tabaid_polygon_photos", "ref_photo"),
            ("tab_photos", "id_photo", "tabaid_section_photos", "ref_photo"),
            ("tab_drawings", "id_drawing", "tabaid_section_drawings", "ref_drawing"),
        ]

        for parent_table, parent_column, child_table, child_column in expected_matches:
            with self.subTest(parent=f"{parent_table}.{parent_column}", child=f"{child_table}.{child_column}"):
                parent_length = _varchar_length(self.template_sql, parent_table, parent_column)
                child_length = _varchar_length(self.template_sql, child_table, child_column)
                self.assertEqual(
                    child_length,
                    parent_length,
                    f"{child_table}.{child_column} should match {parent_table}.{parent_column}",
                )

    def test_auth_template_creates_expected_database_and_users_table(self) -> None:
        self.assertIn("CREATE DATABASE auth_db OWNER app_terrain_db ENCODING 'UTF8';", self.auth_sql)
        self.assertRegex(
            self.auth_sql,
            re.compile(r"CREATE TABLE\s+app_users\s*\(", re.IGNORECASE),
        )


if __name__ == "__main__":
    unittest.main()
