import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv


load_dotenv()
db_url = os.getenv("DATABASE_URL")

if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

print("Testing supabase connection....")


try:
    engine = create_engine(db_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();"))
        print("Connected successfully to:", result.fetchone()[0][:40], "...\n")
except Exception as e:
    print("Connection failed:", e)
    exit()



primary_tables = [
    "patients", "claims", "claims_transactions", 
    "encounters", "providers", "payers", "organizations"
]

raw_dir = "data/raw"
print("Inspecting CSV Headers & Row Counts:\n" + "="*50)

for table in primary_tables:
    file_path = os.path.join(raw_dir, f"{table}.csv")
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, nrows=5)
        total_rows = sum(1 for _ in open(file_path, encoding="utf-8")) - 1
        print(f"File: {table}.csv ({total_rows} rows)")
        print(f"Columns: {list(df.columns)}\n")
    else:
        print(f"Missing: {table}.csv not found in {raw_dir}!\n")
