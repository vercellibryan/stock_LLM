import sqlite3
from pathlib import Path

db_path = Path("../stocks.db")
schema_path = Path("db.sql")

conn = sqlite3.connect(db_path)
with open(schema_path, "r", encoding="utf-8") as f:
    conn.executescript(f.read())
conn.commit()
conn.close()