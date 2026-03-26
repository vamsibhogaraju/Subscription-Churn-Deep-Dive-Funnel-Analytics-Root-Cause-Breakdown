import psycopg2
import pandas as pd

DB = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "kkbox",
    "user":     "postgres",
    "password": "password",
}

try:
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name, column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name IN ('members', 'user_logs', 'transactions', 'user_engagement');
    """)
    rows = cur.fetchall()
    for row in rows:
        print(row)
    conn.close()
except Exception as e:
    print(f"Error: {e}")
