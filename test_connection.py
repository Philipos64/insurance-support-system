import os
import psycopg  # <--- CHANGE 1: We import 'psycopg', NOT 'psycopg2'
from dotenv import load_dotenv

load_dotenv()

print("Attempting to connect with Psycopg 3...")

try:
    # CHANGE 2: The connect syntax is slightly cleaner, but arguments are the same
    # We use a context manager ('with') which Psycopg 3 handles beautifully
    with psycopg.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"), # Note: v3 prefers 'dbname' over 'database'
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT")
    ) as conn:

        # Open a cursor to perform database operations
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            db_version = cur.fetchone()

            print("\nSUCCESS! Connected to PostgreSQL using Psycopg 3:")
            print(db_version[0])

            # Check if your table exists yet
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            tables = cur.fetchall()
            print("\nTables in database:", tables)

except Exception as e:
    print("\nCONNECTION FAILED")
    print(e)