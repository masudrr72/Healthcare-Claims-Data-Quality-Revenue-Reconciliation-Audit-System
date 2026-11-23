
CREATE TABLE IF NOT EXISTS staging.patients AS
SELECT 
    "Id" AS patient_id,
    NULLIF("BIRTHDATE", '')::DATE AS birthdate,
    NULLIF("DEATHDATE", '')::DATE AS deathdate,
    "FIRST" AS first_name,
    "LAST" AS last_name,
    "GENDER" AS gender,
    "STATE" AS state,
    "ZIP" AS zip,
    "HEALTHCARE_EXPENSES" AS healthcare_expenses,
    "HEALTHCARE_COVERAGE" AS healthcare_coverage
FROM raw.patients;

ALTER TABLE staging.patients ADD PRIMARY KEY (patient_id);


CREATE TABLE IF NOT EXISTS staging.claims AS
SELECT 
    "Id" AS claim_id,
    "PATIENTID" AS patient_id,
    "PROVIDERID" AS provider_id,
    "PRIMARYPATIENTINSURANCEID" AS primary_payer_id,
    "DIAGNOSIS1" AS diagnosis_1,
    "DIAGNOSIS2" AS diagnosis_2,
    NULLIF("SERVICEDATE", '')::TIMESTAMP AS service_date,
    "STATUS1" AS status_1,
    "STATUSP" AS status_p,
    COALESCE("OUTSTANDING1", 0) AS outstanding_1,
    COALESCE("OUTSTANDINGP", 0) AS outstanding_p
FROM raw.claims;

ALTER TABLE staging.claims ADD PRIMARY KEY (claim_id);


CREATE TABLE IF NOT EXISTS staging.claims_transactions AS
SELECT 
    "ID" AS transaction_id,
    "CLAIMID" AS claim_id,
    "CHARGEID" AS charge_id,
    "PATIENTID" AS patient_id,
    "TYPE" AS transaction_type,
    COALESCE("AMOUNT", 0) AS amount,
    "METHOD" AS payment_method,
    NULLIF("FROMDATE", '')::TIMESTAMP AS from_date,
    NULLIF("TODATE", '')::TIMESTAMP AS to_date,
    "PROCEDURECODE" AS procedure_code,
    "MODIFIER1" AS modifier_1,
    "UNITS" AS units,
    "NOTES" AS notes,
    "LINENOTE" AS line_note,
    COALESCE("PAYMENTS", 0) AS payments,
    COALESCE("ADJUSTMENTS", 0) AS adjustments,
    COALESCE("OUTSTANDING", 0) AS outstanding,
    "PROVIDERID" AS provider_id
FROM raw.claims_transactions;

ALTER TABLE staging.claims_transactions ADD PRIMARY KEY (transaction_id);


CREATE INDEX idx_stg_claims_patient ON staging.claims(patient_id);
CREATE INDEX idx_stg_tx_claim ON staging.claims_transactions(claim_id);
CREATE INDEX idx_stg_tx_type ON staging.claims_transactions(transaction_type);
