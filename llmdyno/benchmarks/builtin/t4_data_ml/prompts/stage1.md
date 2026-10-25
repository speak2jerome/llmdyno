You are working in /workspace. The `data/` folder contains raw exports from a subscription product. Build a reproducible data pipeline, an analysis and a churn model.

## Files

- `data/customers.csv`: customer_id, signup_date, country, age, plan
- `data/events.jsonl`: one JSON object per line with customer_id, ts (UTC, ISO-8601), event_type (`login`, `page_view`, `purchase` or `support_ticket`) and amount (purchases only; a number or a numeric string)
- `data/labels_train.csv`: customer_id, churned (0/1) for the training customers
- `data/test_ids.csv`: customer_id for the customers you must score

## Cleaning rules (follow exactly)

1. **Customers:** `signup_date` appears as `YYYY-MM-DD`, `YYYY/MM/DD` or `YYYY-MM-DDTHH:MM:SS`. Some customer_ids appear more than once; keep only the row with the latest signup_date.
2. **Country:** normalize to ISO-3166 alpha-2, uppercase. Raw values may be alpha-2 codes, alpha-3 codes or English country names, in any case and with surrounding whitespace. `UK` means GB and `U.S.` means US. The countries present are US, GB, DE, IN, FR, BR, JP and CA.
3. **Plan:** lowercase and strip it (`basic`, `pro`, `enterprise`).
4. **Age:** a missing age, or one outside 16–100, is invalid. Impute invalid ages with the median of the valid ages, computed after deduplication.
5. **Events:** drop exact duplicate events (same customer_id, ts, event_type and amount), and drop events whose customer_id is not in the cleaned customers table. Treat amount as a float.

## Deliverables

- `pipeline.py`: running `python pipeline.py` from /workspace regenerates every output below from the raw data. It must finish in under 5 minutes.
- `output/features.parquet`: one row per cleaned customer, with at least these columns:
  - customer_id, signup_date, country, plan, age
  - n_events, n_purchases, total_amount (sum of purchase amounts), n_support_tickets
  - days_since_last_event: days from the date of the customer's last event to 2026-06-30. If the customer has no events, use days from signup_date to 2026-06-30.
  - churned: 0/1 for training customers, empty/null for the others
- `output/warehouse.db`: a SQLite database with a table `features` containing the same rows and columns.
- `output/summary.json` with exactly these keys:
  - `"n_customers"`: number of customers after cleaning
  - `"n_events_clean"`: number of events after cleaning
  - `"train_churn_rate"`: churn rate among the training customers, rounded to 4 decimals
  - `"median_age"`: median of the valid ages, before imputation
  - `"top_countries_by_revenue"`: the 3 country codes with the highest total purchase revenue, highest first
  - `"revenue_by_month_2026"`: `{"2026-01": revenue, ..., "2026-06": revenue}`, the total purchase amount per calendar month (UTC), rounded to 2 decimals
- `output/report.md`: a short analysis report for a business audience, with:
  - the key numbers above
  - a revenue-by-month table
  - the main drivers of churn you found
  - how your model performs
- A churn model trained only on the training customers, with:
  - `output/predictions.csv`: columns customer_id and churn_probability, for every customer in `data/test_ids.csv`
  - `output/metrics.json`: `{"model": <short description>, "cv_auc": <5-fold cross-validated ROC AUC on the training customers>}`

pandas, numpy, pyarrow, scikit-learn, scipy and matplotlib are installed. There is no internet access, so do not install anything. When you are finished, reply with a short summary that includes the cross-validated AUC.
