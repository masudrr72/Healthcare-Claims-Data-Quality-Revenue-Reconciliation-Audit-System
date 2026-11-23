
SELECT 'patients' AS table_name, COUNT(*) AS row_count FROM raw.patients
UNION ALL
SELECT 'encounters', COUNT(*) FROM raw.encounters
UNION ALL
SELECT 'claims', COUNT(*) FROM raw.claims
UNION ALL
SELECT 'claims_transactions', COUNT(*) FROM raw.claims_transactions;


SELECT 
    "TYPE", 
    "METHOD",
    COUNT(*) AS total_transactions,
    ROUND(SUM("AMOUNT"), 2) AS total_amount,
    ROUND(AVG("AMOUNT"), 2) AS avg_amount
FROM raw.claims_transactions
GROUP BY "TYPE", "METHOD"
ORDER BY total_transactions DESC;
