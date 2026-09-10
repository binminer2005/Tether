import os
import sqlite3
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
SOURCE_DB = ROOT / "Tether" / "tether.sqlite3"
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tether")

TABLES = [
    "users",
    "submissions",
    "editorial_articles",
    "editorial_article_blocks",
]


def fetch_sqlite_columns(conn, table_name):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]


def main():
    sqlite_conn = sqlite3.connect(SOURCE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    try:
        with psycopg.connect(DSN) as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT 1")
                print(f"Connected to PostgreSQL: {DSN}")

                # Ensure the app schema exists before data migration.
                import importlib.util

                env = os.environ.copy()
                env["DATABASE_URL"] = DSN
                os.environ["DATABASE_URL"] = DSN
                spec = importlib.util.spec_from_file_location("tether_app", ROOT / "Tether" / "app.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                with module.app.app_context():
                    module.init_db()
                    print("PostgreSQL schema initialized.")

                for table_name in reversed(TABLES):
                    cur.execute(f"DELETE FROM {table_name}")

                for table_name in TABLES:
                    columns = fetch_sqlite_columns(sqlite_conn, table_name)
                    if not columns:
                        continue
                    placeholders = ", ".join(["%s"] * len(columns))
                    insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    rows = sqlite_conn.execute(f"SELECT * FROM {table_name}").fetchall()
                    for row in rows:
                        values = tuple(row[col] for col in columns)
                        cur.execute(insert_sql, values)
                    if "id" in columns and rows:
                        cur.execute(
                            "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE(MAX(id), 1), TRUE) FROM "
                            + table_name,
                            (table_name,),
                        )
                    print(f"Migrated {table_name}: {len(rows)} rows")

                pg_conn.commit()
                print("Migration complete.")
    finally:
        sqlite_conn.close()


if __name__ == "__main__":
    main()
