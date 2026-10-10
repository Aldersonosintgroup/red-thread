"""Minimal, idempotent schema migrations for SQLite. This app has no Alembic
setup; create_all only creates missing tables, never adds columns to tables
that already exist on a user's live database, so new columns need an
explicit, safe-to-rerun ADD COLUMN step."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# (table, column, column_type_sql)
NEW_COLUMNS = [
    ("cases", "notes", "TEXT"),
    ("actors", "custom_color", "VARCHAR"),
    ("documents", "phash", "VARCHAR"),
    ("documents", "rotation", "INTEGER DEFAULT 0"),
    ("timeline_events", "excluded", "BOOLEAN NOT NULL DEFAULT 0"),
]


def run_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, column, column_type in NEW_COLUMNS:
            if table not in existing_tables:
                continue  # create_all will create this table with the column already present
            existing_columns = {col["name"] for col in inspector.get_columns(table)}
            if column not in existing_columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
