import os
import io
import time
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")

if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

tables = [
    "payers",
    "organizations",
    "providers",
    "patients",
    "encounters",
    "claims",
    "claims_transactions"
]

raw_dir = "data/raw"

def fast_copy_to_postgres(df, table_name, raw_conn):
    cursor = raw_conn.cursor()
    output = io.StringIO()
    df.to_csv(output, sep='\t', header=False, index=False, na_rep='\\N')
    output.seek(0)
    
    columns = ', '.join([f'"{col}"' for col in df.columns])
    sql = f'COPY raw.{table_name} ({columns}) FROM STDIN WITH (FORMAT CSV, DELIMITER E\'\\t\', NULL \'\\N\')'
    
    with cursor.copy(sql) as copy:
        copy.write(output.getvalue())
    raw_conn.commit()

print("Starting fast data ingestion into Supabase (raw schema)...\n")

for table in tables:
    file_path = os.path.join(raw_dir, f"{table}.csv")
    if not os.path.exists(file_path):
        print(f"Skipping {table}: file not found.")
        continue

    start_time = time.time()
    print(f"Loading {table}.csv...")

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE raw.{table};"))

    raw_conn = engine.raw_connection()
    total_inserted = 0
    try:
        for chunk in pd.read_csv(file_path, chunksize=50000, low_memory=False):
            for col in ['FIPS', 'ZIP', 'NPI', 'CODE', 'REASONCODE', 'PROCEDURECODE', 'MODIFIER1', 'MODIFIER2']:
                if col in chunk.columns:
                    chunk[col] = chunk[col].astype(str).replace({'nan': None, 'None': None, '<NA>': None})
                    chunk[col] = chunk[col].str.replace(r'\.0$', '', regex=True)

            fast_copy_to_postgres(chunk, table, raw_conn)
            total_inserted += len(chunk)
            print(f"   -> Inserted {total_inserted} rows...")
    finally:
        raw_conn.close()

    elapsed = round(time.time() - start_time, 2)
    print(f"Completed raw.{table}: {total_inserted} rows in {elapsed}s\n")

print("All raw healthcare data successfully loaded into Supabase!")
