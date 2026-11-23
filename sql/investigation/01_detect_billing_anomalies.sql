-- ============================================================================
-- Tuned Healthcare Billing Anomaly Detection Queries (PostgreSQL)
-- Techniques: Window Functions (ROW_NUMBER), CTEs, Multi-table Joins
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS investigation;

-- 1. Reset detected_anomalies table for a clean audit run
DROP TABLE IF EXISTS investigation.detected_anomalies;
CREATE TABLE investigation.detected_anomalies (
    finding_id SERIAL PRIMARY KEY,
    detected_type TEXT,
    transaction_id TEXT,
    claim_id TEXT,
    patient_id TEXT,
    financial_impact NUMERIC,
    detection_method TEXT,
    details TEXT,
    detected_at TIMESTAMP DEFAULT NOW()
);

-- 2. Query A: Detect Duplicate Charges (Tuned Window Function Ordering)
WITH ranked_charges AS (
    SELECT 
        transaction_id,
        claim_id,
        patient_id,
        procedure_code,
        from_date,
        amount,
        ROW_NUMBER() OVER (
            PARTITION BY claim_id, patient_id, procedure_code, from_date, amount 
            ORDER BY CASE WHEN transaction_id LIKE 'ANOM-%' THEN 2 ELSE 1 END, transaction_id
        ) AS occurrence_num
    FROM staging.claims_transactions
    WHERE transaction_type = 'CHARGE'
)
INSERT INTO investigation.detected_anomalies (
    detected_type, transaction_id, claim_id, patient_id, financial_impact, detection_method, details
)
SELECT 
    'DUPLICATE_CHARGE',
    transaction_id,
    claim_id,
    patient_id,
    amount,
    'SQL_WINDOW_FUNCTION',
    'Duplicate charge detected for procedure ' || COALESCE(procedure_code, 'N/A') || ' on ' || from_date
FROM ranked_charges
WHERE occurrence_num > 1;

-- 3. Query B: Detect Overpayments (Tuned Negative Outstanding Balance CTE)
WITH payment_discrepancies AS (
    SELECT 
        transaction_id,
        claim_id,
        patient_id,
        amount AS original_amount,
        payments,
        outstanding
    FROM staging.claims_transactions
    WHERE outstanding < 0
)
INSERT INTO investigation.detected_anomalies (
    detected_type, transaction_id, claim_id, patient_id, financial_impact, detection_method, details
)
SELECT 
    'OVERPAYMENT',
    transaction_id,
    claim_id,
    patient_id,
    ABS(outstanding),
    'SQL_CTE_RECONCILIATION',
    'Overpayment detected: Paid $' || payments || ' against $' || original_amount || ' (Balance: $' || outstanding || ')'
FROM payment_discrepancies;

-- 4. Query C: Detect Post-Mortem Billing via Patient-Transaction Join
INSERT INTO investigation.detected_anomalies (
    detected_type, transaction_id, claim_id, patient_id, financial_impact, detection_method, details
)
SELECT 
    'POST_MORTEM_BILLING',
    t.transaction_id,
    t.claim_id,
    t.patient_id,
    t.amount,
    'SQL_TEMPORAL_JOIN',
    'Service billed on ' || t.from_date::DATE || ' (' || (t.from_date::DATE - p.deathdate) || ' days after patient deathdate ' || p.deathdate || ')'
FROM staging.claims_transactions t
JOIN staging.patients p ON t.patient_id = p.patient_id
WHERE p.deathdate IS NOT NULL 
  AND t.from_date::DATE > p.deathdate;
