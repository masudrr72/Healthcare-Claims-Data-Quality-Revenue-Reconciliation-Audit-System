import os
import re
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

print("Running Tuned Python Regex Validator & Ground Truth Reconciliation...\n")

# 1. Fetch non-null procedure codes from staging
query = """
    SELECT transaction_id, claim_id, patient_id, procedure_code, amount
    FROM staging.claims_transactions
    WHERE procedure_code IS NOT NULL AND procedure_code != '';
"""
df = pd.read_sql(query, engine)

# 2. Validate procedure codes using refined Regex (valid CPT/SNOMED/HCPCS codes: 5-18 alphanumeric chars, no ERR- prefix)
valid_code_pattern = re.compile(r'^(?!ERR-)[A-Z0-9]{5,18}$')

malformed_records = []
for _, row in df.iterrows():
    code = str(row['procedure_code']).strip()
    if not valid_code_pattern.match(code):
        malformed_records.append({
            'detected_type': 'MALFORMED_CPT_CODE',
            'transaction_id': row['transaction_id'],
            'claim_id': row['claim_id'],
            'patient_id': row['patient_id'],
            'financial_impact': float(row['amount'] or 0.0),
            'detection_method': 'PYTHON_REGEX_VALIDATOR',
            'details': f"Non-standard procedure code format detected via regex: '{code}'"
        })

malformed_df = pd.DataFrame(malformed_records)
print(f"Regex Engine detected {len(malformed_df)} malformed procedure codes.")

# 3. Clean old regex findings and insert new findings
with engine.begin() as conn:
    conn.execute(text("DELETE FROM investigation.detected_anomalies WHERE detection_method = 'PYTHON_REGEX_VALIDATOR';"))

if not malformed_df.empty:
    malformed_df.to_sql(
        'detected_anomalies', 
        engine, 
        schema='investigation', 
        if_exists='append', 
        index=False
    )
    print("Saved Python Regex findings into 'investigation.detected_anomalies'.")

# 4. Reconcile against Ground Truth
reconciliation_sql = """
    SELECT 
        g.anomaly_type,
        COUNT(DISTINCT g.record_id) AS total_injected,
        COUNT(DISTINCT d.transaction_id) AS total_caught,
        ROUND(
            (COUNT(DISTINCT d.transaction_id)::NUMERIC / COUNT(DISTINCT g.record_id)) * 100, 2
        ) AS recall_percentage
    FROM investigation.injected_anomalies_log g
    LEFT JOIN investigation.detected_anomalies d 
        ON g.record_id = d.transaction_id 
        AND g.anomaly_type = d.detected_type
    GROUP BY g.anomaly_type
    ORDER BY g.anomaly_type;
"""

audit_summary = pd.read_sql(reconciliation_sql, engine)

print("\n" + "="*65)
print("FINAL AUDIT RECONCILIATION REPORT (GROUND TRUTH RECALL)")
print("="*65)
print(audit_summary.to_string(index=False))
print("="*65)

os.makedirs("reports", exist_ok=True)
audit_summary.to_csv("reports/final_audit_reconciliation.csv", index=False)
print("\nReport exported to 'reports/final_audit_reconciliation.csv'.")
