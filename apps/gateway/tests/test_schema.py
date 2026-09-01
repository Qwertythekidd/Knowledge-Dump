from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_mock_engine, inspect

from apps.gateway.knowledge_dump_gateway.schema import metadata
from apps.gateway.knowledge_dump_gateway.store import Catalog


class SchemaTests(unittest.TestCase):
    def test_schema_compiles_for_postgresql(self) -> None:
        statements: list[str] = []
        engine = create_mock_engine(
            "postgresql+psycopg://",
            lambda sql, *multiparams, **params: statements.append(str(sql.compile(dialect=engine.dialect))),
        )
        metadata.create_all(engine, checkfirst=False)
        rendered = "\n".join(statements)
        self.assertIn("CREATE TABLE accounts", rendered)
        self.assertIn("CREATE TABLE file_versions", rendered)
        self.assertIn("CREATE TABLE audit_events", rendered)
        self.assertIn("CREATE TABLE upload_sessions", rendered)
        self.assertIn("CREATE TABLE upload_parts", rendered)
        self.assertIn("CREATE TABLE download_grants", rendered)

    def test_legacy_mock_schema_is_preserved_before_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.db"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE sessions (token TEXT PRIMARY KEY, account_id TEXT);
                    CREATE TABLE files (id TEXT PRIMARY KEY, account_id TEXT);
                    CREATE TABLE activity (id TEXT PRIMARY KEY, account_id TEXT);
                    """
                )
            catalog = Catalog(path)
            names = set(inspect(catalog.engine).get_table_names())
            self.assertIn("accounts", names)
            self.assertIn("file_versions", names)
            self.assertTrue(any(name.startswith("legacy_files_") for name in names))
            self.assertIsNotNone(catalog.account_by_email("demo@knowledge-dump.local"))


if __name__ == "__main__":
    unittest.main()
