# 🏥 Healthcare Billing Anomaly Investigation & Audit Pipeline

An end-to-end Revenue Cycle Management (RCM) data engineering and billing investigation system built with **PostgreSQL (Supabase)**, **Python**, **SQL (Window Functions & CTEs)**, **Regex**, and **Streamlit**.

---


## 🖥️ Investigation Dashboard Preview

### 1. Audit Summary & Ground Truth Recall Metrics
![Dashboard Overview](docs/dashboard_overview1.png)

### 2. Interactive Billing Investigation Issue Queue
![Issue Queue](docs/dashboard_overview2.png)

---

## 🎯 Project Overview
U.S. healthcare billing workflows generate massive volumes of claims and line-item ledger transactions where coding errors, duplicate charges, overpayments, and temporal discrepancies often occur. This project simulates a production billing audit pipeline:
1. **Synthetic Data Generation:** Generated realistic, relational U.S. healthcare records (patients, encounters, providers, payers, claims, and 250k+ financial transactions) using **Synthea**.
2. **Multi-Layer Database Architecture:** Designed a 3-tier schema (`raw`, `staging`, `investigation`) on cloud-hosted **PostgreSQL (Supabase)** with optimized indexing and type casting.
3. **Deterministic Anomaly Injection:** Built a seeded Python anomaly generator to inject 70 controlled billing errors across 4 real-world RCM categories with a reproducible ground truth audit log.
4. **SQL & Regex Detection Engine:** Combined PostgreSQL **Window Functions (`ROW_NUMBER`)**, **CTEs**, **Temporal Joins**, and **Python Regular Expressions (`re`)** to achieve **100% recall** on injected anomalies.
5. **Investigation Workflow UI:** Built an interactive **Streamlit** issue queue dashboard for triaging flagged anomalies by financial exposure and exporting audit reports.

---

## 🏗️ System Architecture

```text
[Synthea Generator] ──▶ [Raw CSV Landing (data/raw)]
                               │
                               ▼ (PostgreSQL COPY Protocol)
                     [Supabase: raw schema]
                               │
                               ▼ (Type Casting & Indexing)
                   [Supabase: staging schema] ◀── [Python Anomaly Injector]
                               │                         │
             ┌─────────────────┴─────────────────┐       ▼
             ▼                                   ▼  [Ground Truth Log]
  [SQL Investigation Engine]          [Python Regex Validator]
  (Window Functions & CTEs)           (Pattern Matching Engine)
             │                                   │
             └─────────────────┬─────────────────┘
                               ▼
                 [Supabase: investigation schema]
                               │
                               ▼
              [Streamlit Issue Queue & CSV Reports]
```

---

## 🔍 Billing Anomalies Detected & Audit Results

| Anomaly Category | Detection Technique | Technical Logic | Injected | Recall |
| :--- | :--- | :--- | :---: | :---: |
| **Duplicate Charges** | SQL Window Function | `ROW_NUMBER() OVER (PARTITION BY claim_id, patient_id, procedure_code, from_date, amount)` | 25 | **100.0%** |
| **Post-Mortem Billing** | SQL Temporal Join | Joined `claims_transactions` with `patients` where `service_date > deathdate` | 15 | **100.0%** |
| **Malformed CPT/SNOMED Codes** | Python Regex (`re`) | Validated procedure code syntax against `^(?!ERR-)[A-Z0-9]{5,18}$` | 30 | **100.0%** |
| **Overpayments / Negative Balance** | SQL CTE Reconciliation | Isolated transactions with `outstanding < 0` for ledger reconciliation | — | Verified |

---

## 📂 Repository Structure

```text
healthcare-billing-investigation/
├── data/
│   ├── test_anomalies/          # Reproducible ground truth anomaly logs
│   └── ...
├── database/
│   ├── schema/                  # DDL scripts for raw & staging schemas
│   └── imports/                 # High-speed PostgreSQL COPY ingestion script
├── sql/
│   ├── profiling/               # Exploratory data profiling queries
│   └── investigation/           # Core anomaly detection SQL queries (CTEs, Window Functions)
├── src/
│   ├── data_generation/         # Schema inspection & DB connection utilities
│   ├── anomaly_injection/       # Deterministic billing anomaly generator
│   └── validators/              # Python Regex engine & ground truth reconciliation
├── retool/
│   └── app.py                   # Interactive Streamlit Issue Queue Dashboard
├── reports/                     # Exported audit summary reports
├── requirements.txt
└── README.md
```

---

## 🚀 How to Run Locally

1. **Clone the repository & install dependencies:**
   ```bash
   git clone https://github.com
   cd healthcare-billing-investigation
   pip install -r requirements.txt
   ```
2. **Configure Database Connection:**
   Create a `.env` file in the root directory:
   ```env
   DATABASE_URL=postgresql://user:password@host:port/postgres
   ```
3. **Execute the Pipeline:**
   ```bash
   python database/imports/load_raw_data.py
   python src/anomaly_injection/inject_anomalies.py
   python src/validators/regex_and_audit_validator.py
   ```
4. **Launch the Investigation Dashboard:**
   ```bash
   python -m streamlit run retool/app.py
   ```
