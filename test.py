import sqlite3

DB_FILE = "users.db"


def inspect_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    print("=" * 50)
    print(f"DATABASE: {DB_FILE}")
    print(f"TABLES FOUND ({len(tables)}): {', '.join(tables)}")
    print("=" * 50)

    # 2. Inspect structure and contents for each table
    for table in tables:
        print(f"\n--- TABLE: {table} ---")

        # Get column names
        cursor.execute(f"PRAGMA table_info({table});")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"COLUMNS: {columns}")

        # Get rows
        cursor.execute(f"SELECT * FROM {table};")
        rows = cursor.fetchall()
        print(f"ROW COUNT: {len(rows)}")

        if rows:
            print("DATA:")
            for row in rows:
                print(" ", row)
        else:
            print(" (Table is empty)")

    conn.close()


if __name__ == "__main__":
    inspect_database()
