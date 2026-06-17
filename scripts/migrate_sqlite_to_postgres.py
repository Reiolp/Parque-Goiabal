"""
Copy data from local SQLite `goiabal.db` to a remote PostgreSQL database.

Usage:
  Set environment variable `TARGET_DATABASE_URL` (e.g. postgres://user:pass@host:5432/dbname)
  then run:
    python scripts/migrate_sqlite_to_postgres.py

This script reflects the tables and attempts to insert rows into the target DB.
It will skip rows that violate unique constraints.
"""
import os
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.exc import IntegrityError


def main():
    base_dir = os.path.abspath(os.path.dirname(__file__) + os.sep + '..')
    sqlite_path = os.path.join(base_dir, 'goiabal.db')
    if not os.path.exists(sqlite_path):
        print('Local SQLite DB not found at', sqlite_path)
        return

    target_url = os.environ.get('TARGET_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not target_url:
        print('Set TARGET_DATABASE_URL or DATABASE_URL environment variable to the Postgres connection string')
        return

    src_engine = create_engine(f'sqlite:///{sqlite_path.replace("\\", "/")}')
    dst_engine = create_engine(target_url)

    src_meta = MetaData()
    dst_meta = MetaData()

    # reflect only known tables to avoid surprises
    tables = ['users', 'registros', 'denuncias', 'curtidas']
    src_meta.reflect(bind=src_engine, only=tables)
    dst_meta.reflect(bind=dst_engine, only=tables)

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        for name in tables:
            if name not in src_meta.tables:
                print(f"Skipping missing table in source: {name}")
                continue
            src_table = Table(name, src_meta, autoload_with=src_engine)
            if name not in dst_meta.tables:
                print(f"Target missing table {name}; creating table by reflecting source schema is not automatic. Ensure target has the schema created (app will create tables on startup). Skipping {name}.")
                continue
            dst_table = Table(name, dst_meta, autoload_with=dst_engine)

            rows = src_conn.execute(select(src_table)).mappings().all()
            print(f"Copying {len(rows)} rows into {name}...")
            inserted = 0
            for row in rows:
                try:
                    dst_conn.execute(dst_table.insert(), row)
                    inserted += 1
                except IntegrityError:
                    # skip duplicates / conflicts
                    dst_conn.rollback()
                except Exception as e:
                    print('Error inserting row into', name, e)
            print(f"Inserted {inserted}/{len(rows)} rows into {name}")


if __name__ == '__main__':
    main()
