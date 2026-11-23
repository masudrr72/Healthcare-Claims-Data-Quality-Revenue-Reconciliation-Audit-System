import os
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

print("Starting Controlled Billing Anomaly Injection...\n")

with engine.begin() as conn:
    # Clean up previously injected anomalies to ensure idempotency
    conn.execute(text("DELETE FROM staging.claims_transactions WHERE transaction_id LIKE 'ANOM-%';"))
    
    # Create ground truth audit log table
    conn.execute(text("""
        DROP TABLE IF EXISTS investigation.injected_anomalies_log;
        CREATE TABLE investigation.injected_anomalies_log (
            anomaly_id SERIAL PRIMARY KEY,
            anomaly_type TEXT,
            target_table TEXT,
            record_id TEXT,
            claim_id TEXT,
            patient_id TEXT,
            description TEXT,
            injected_at TIMESTAMP DEFAULT NOW()
        );
    """))

    # Scenario 1: Duplicate Charge (25 deterministic cases)
    dup_sql = """
        WITH sample_charges AS (
            SELECT * FROM staging.claims_transactions 
            WHERE transaction_type = 'CHARGE' AND amount > 50
            ORDER BY md5(transaction_id || 'seed42') LIMIT 25
        ),
        inserted AS (
            INSERT INTO staging.claims_transactions (
                transaction_id, claim_id, charge_id, patient_id, transaction_type, 
                amount, payment_method, from_date, to_date, procedure_code, 
                modifier_1, units, notes, line_note, payments, adjustments, outstanding, provider_id
            )
            SELECT 
                'ANOM-DUP-' || substr(md5(transaction_id), 1, 12),
                claim_id, charge_id, patient_id, transaction_type,
                amount, payment_method, from_date, to_date, procedure_code,
                modifier_1, units, 'Duplicate automated charge entry', line_note, payments, adjustments, outstanding, provider_id
            FROM sample_charges
            RETURNING transaction_id, claim_id, patient_id, amount
        )
        INSERT INTO investigation.injected_anomalies_log (anomaly_type, target_table, record_id, claim_id, patient_id, description)
        SELECT 'DUPLICATE_CHARGE', 'staging.claims_transactions', transaction_id, claim_id, patient_id, 
               'Exact duplicate charge injected for amount: $' || amount
        FROM inserted;
    """
    conn.execute(text(dup_sql))
    print("1/4: Injected 25 DUPLICATE_CHARGE anomalies.")

    # Scenario 2: Overpayment / Negative Outstanding Balance (20 cases)
    overpay_sql = """
        WITH target_tx AS (
            SELECT transaction_id, claim_id, patient_id, amount 
            FROM staging.claims_transactions 
            WHERE transaction_type = 'PAYMENT' AND amount > 100
              AND transaction_id NOT LIKE 'ANOM-%'
            ORDER BY md5(transaction_id || 'overpay') LIMIT 20
        ),
        updated AS (
            UPDATE staging.claims_transactions t
            SET payments = t.amount * 2.5,
                outstanding = -(t.amount * 1.5),
                notes = COALESCE(t.notes, '') || ' [SYS_ERR: Overpayment applied]'
            FROM target_tx x
            WHERE t.transaction_id = x.transaction_id
            RETURNING t.transaction_id, t.claim_id, t.patient_id, t.payments
        )
        INSERT INTO investigation.injected_anomalies_log (anomaly_type, target_table, record_id, claim_id, patient_id, description)
        SELECT 'OVERPAYMENT', 'staging.claims_transactions', transaction_id, claim_id, patient_id,
               'Payment exceeds billed amount; negative outstanding created: $' || payments
        FROM updated;
    """
    conn.execute(text(overpay_sql))
    print("2/4: Injected 20 OVERPAYMENT anomalies.")

    # Scenario 3: Malformed CPT/Procedure Code Format (30 cases for regex validation)
    regex_sql = """
        WITH target_codes AS (
            SELECT transaction_id, claim_id, patient_id, procedure_code
            FROM staging.claims_transactions
            WHERE procedure_code IS NOT NULL AND procedure_code != ''
              AND transaction_id NOT LIKE 'ANOM-%'
            ORDER BY md5(transaction_id || 'regex') LIMIT 30
        ),
        updated AS (
            UPDATE staging.claims_transactions t
            SET procedure_code = 'ERR-' || COALESCE(t.procedure_code, '000') || 'X',
                line_note = 'Manual override code entry'
            FROM target_codes x
            WHERE t.transaction_id = x.transaction_id
            RETURNING t.transaction_id, t.claim_id, t.patient_id, t.procedure_code
        )
        INSERT INTO investigation.injected_anomalies_log (anomaly_type, target_table, record_id, claim_id, patient_id, description)
        SELECT 'MALFORMED_CPT_CODE', 'staging.claims_transactions', transaction_id, claim_id, patient_id,
               'Invalid non-standard CPT/SNOMED code format: ' || procedure_code
        FROM updated;
    """
    conn.execute(text(regex_sql))
    print("3/4: Injected 30 MALFORMED_CPT_CODE anomalies.")

    # Scenario 4: Post-Mortem Billing (up to 15 deceased patient cases)
    postmortem_sql = """
        WITH deceased_patients AS (
            SELECT patient_id, deathdate 
            FROM staging.patients 
            WHERE deathdate IS NOT NULL 
            LIMIT 15
        ),
        sample_claims AS (
            SELECT DISTINCT ON (c.patient_id) c.claim_id, c.patient_id, c.provider_id, d.deathdate
            FROM staging.claims c
            JOIN deceased_patients d ON c.patient_id = d.patient_id
        ),
        inserted AS (
            INSERT INTO staging.claims_transactions (
                transaction_id, claim_id, charge_id, patient_id, transaction_type,
                amount, from_date, to_date, procedure_code, units, notes, provider_id
            )
            SELECT 
                'ANOM-PM-' || substr(md5(claim_id), 1, 12),
                claim_id, 'CHG-PM-999', patient_id, 'CHARGE',
                450.00,
                (deathdate + INTERVAL '45 days')::TIMESTAMP,
                (deathdate + INTERVAL '45 days')::TIMESTAMP,
                '99214', 1, 'Routine follow-up visit post-discharge', provider_id
            FROM sample_claims
            RETURNING transaction_id, claim_id, patient_id, from_date
        )
        INSERT INTO investigation.injected_anomalies_log (anomaly_type, target_table, record_id, claim_id, patient_id, description)
        SELECT 'POST_MORTEM_BILLING', 'staging.claims_transactions', transaction_id, claim_id, patient_id,
               'Service billed 45 days after patient deathdate on: ' || from_date
        FROM inserted;
    """
    conn.execute(text(postmortem_sql))
    print("4/4: Injected POST_MORTEM_BILLING anomalies.")

# Export ground truth log to CSV for audit verification
log_df = pd.read_sql("SELECT * FROM investigation.injected_anomalies_log;", engine)
os.makedirs("data/test_anomalies", exist_ok=True)
log_df.to_csv("data/test_anomalies/ground_truth_anomalies.csv", index=False)

print(f"\nCompleted! Total {len(log_df)} reproducible anomalies logged to 'data/test_anomalies/ground_truth_anomalies.csv'.")
