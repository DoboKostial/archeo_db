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

    def test_geodetic_point_codes_are_complete_and_migratable(self) -> None:
        enum_match = re.search(
            r"CREATE TYPE\s+geopt_code\s+AS ENUM\s*\((.*?)\)\s*;",
            self.template_sql,
            re.IGNORECASE | re.DOTALL,
        )
        self.assertIsNotNone(enum_match)
        enum_codes = re.findall(r"'([A-Z]{2})'", enum_match.group(1))
        self.assertEqual(enum_codes, ["SU", "FX", "EP", "FO", "NI", "PF", "FI", "PR", "SP"])

        migration = (DB_DIR / "migrations" / "20260815_add_geopt_codes.sql").read_text(
            encoding="utf-8",
        )
        self.assertIn("ADD VALUE IF NOT EXISTS 'FI' BEFORE 'SP'", migration)
        self.assertIn("ADD VALUE IF NOT EXISTS 'PR' BEFORE 'SP'", migration)

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

    def test_excavation_extent_is_common_su_attribute(self) -> None:
        sj_block = _table_block(self.template_sql, "tab_sj")
        negativ_block = _table_block(self.template_sql, "tab_sj_negativ")

        self.assertRegex(sj_block, re.compile(r"\bexcav_extent\s+NUMERIC\(3,0\)", re.IGNORECASE))
        self.assertIn("tab_sj_excav_extent_chk", sj_block)
        self.assertNotRegex(negativ_block, re.compile(r"\bexcav_extent\b", re.IGNORECASE))

    def test_excavation_extent_migration_preserves_existing_values(self) -> None:
        migration = (DB_DIR / "migrations" / "20260813_move_excav_extent_to_su.sql").read_text(
            encoding="utf-8",
        )

        self.assertIn("ADD COLUMN excav_extent NUMERIC(3,0) NULL", migration)
        self.assertIn("SET excav_extent = CASE", migration)
        self.assertIn("WHEN 'whole' THEN 100", migration)
        self.assertIn("WHEN 'more_than_50' THEN 75", migration)
        self.assertIn("WHEN 'around_50' THEN 50", migration)
        self.assertIn("WHEN 'less_than_50' THEN 25", migration)
        self.assertIn("DROP COLUMN excav_extent", migration)
        self.assertIn("tab_sj_excav_extent_chk", migration)

    def test_auth_template_creates_expected_database_and_users_table(self) -> None:
        self.assertIn("CREATE DATABASE auth_db OWNER own_auth_db ENCODING 'UTF8';", self.auth_sql)
        self.assertRegex(
            self.auth_sql,
            re.compile(r"CREATE TABLE\s+(?:public\.)?app_users\s*\(", re.IGNORECASE),
        )

    def test_auth_template_provisions_single_use_mobile_login_grants(self) -> None:
        grant_block = _table_block(self.auth_sql, "public.mobile_login_grants")

        self.assertRegex(grant_block, re.compile(r"\btoken_hash\s+char\(64\)", re.IGNORECASE))
        self.assertRegex(grant_block, re.compile(r"\bexpires_at\s+timestamptz\s+NOT NULL", re.IGNORECASE))
        self.assertRegex(grant_block, re.compile(r"\bused_at\s+timestamptz\s+NULL", re.IGNORECASE))
        self.assertIn("SECURITY DEFINER", self.auth_sql)
        self.assertIn("consume_mobile_login_grant", self.auth_sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.consume_mobile_login_grant(text) TO app_mobile_db",
            self.auth_sql,
        )

    def test_find_count_is_optional_when_not_counted_in_field(self) -> None:
        finds_block = _table_block(self.template_sql, "tab_finds")

        self.assertRegex(finds_block, re.compile(r"\bcount\s+int2\s+NULL\b", re.IGNORECASE))
        self.assertIn("count IS NULL OR count > 0", finds_block)
        self.assertNotRegex(finds_block, re.compile(r"\bcount\s+int2\s+NOT NULL\b", re.IGNORECASE))

    def test_find_box_is_optional_when_not_assigned_in_field(self) -> None:
        finds_block = _table_block(self.template_sql, "tab_finds")

        self.assertRegex(finds_block, re.compile(r"\bbox\s+int2\s+NULL\b", re.IGNORECASE))
        self.assertIn("box IS NULL OR box > 0", finds_block)
        self.assertNotRegex(finds_block, re.compile(r"\bbox\s+int2\s+NOT NULL\b", re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
