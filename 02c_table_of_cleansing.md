# Cleaning contract — yellow taxi trip records

rule: raw row count == processed + rejected, always.

official TLC dictionary:
(https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf)

| # | Issue | Scale | Decision | Rationale |
|---|-------|-------|----------|-----------|
| 1 | Pickup from an absurd year (<2023-01-01 or > today) | per H9b | **REJECT** → rejected/ | Broken device clock; pickup date is the partition key — a row with an untrustworthy date has no place in the lake. |
| 2 | Pickup from the neighboring month (boundary) | per H9a | **KEEP**, partition by the actual date | Late-arriving data; we partition by event date, not by source file name. |
| 3 | Dropoff before pickup | 56 | **REJECT** → rejected/ | Physically impossible; no way to tell which date is wrong. |
| 4 | Duration > 24h | per H8 | **FLAG** `is_duration_outlier` | Likely a taximeter never turned off; time-side cross-field test. |
| 5 | Negative fare **and** total | per H2 | **KEEP + FLAG** `is_refund_like` | Reversals/refunds — business-valid; dropping them would distort revenue sums. |
| 6 | Negative fare XOR total (~1.9k) | per H2 | **FLAG** `is_amount_mismatch` (final decision after H2) | Amounts partially diverge — establish the pattern first, then the verdict. |
| 7 | Negative tip only | 102 | **KEEP + FLAG** `is_tip_correction` (after H3) | Likely credit card tip corrections. |
| 8 | total ≠ sum of components (1-cent tolerance) | per H4 | **FLAG** `is_amount_inconsistent` | Internal consistency test derived directly from the data dictionary definition. |
| 9 | trip_distance = 0 | 60,371 | **KEEP + FLAG** `is_zero_distance` | GPS error / cancelled trip / "in place" — the remaining columns stay useful. |
| 10 | trip_distance > 100 mi | 59 | **FLAG** `is_distance_outlier` | Max 312k mi = error, but individual long trips do exist. |
| 11 | Speed > 80 mph | 1,107 | **FLAG** `is_speed_anomaly` | Distance/time cross-field test from the speed side. |
| 12 | passenger_count 0 or NaN | ~171k | **KEEP** (nullable Int type) | Does not invalidate the trip or the payment; we do not guess zeros. |
| 13 | Missing block in 5 columns at once | 140,162 | **KEEP**, note in quality report | Segment from a different delivery channel (H1), not random failures; 4.7% is too much to drop. |
| 14 | RatecodeID = 99 (sentinel) | per H5 | **FIX: 99 → NA** | Dictionary: 99 = Null/unknown; meaning is 100% certain — the only legal FIX on this list. Cleans future GROUP BYs. |
| 15 | Codes outside the dictionary (payment_type / VendorID / RatecodeID / store_and_fwd_flag) | per H5, H7 | **FLAG** `is_unknown_code` + report entry | An unknown code signals a change in the source, not a reason to drop the row; always validate against the official dictionary. |
| 16 | PU/DO = 264/265 (unknown zone) | per H6 | **KEEP + FLAG** `is_unknown_zone` | Location sentinel; the trip is financially valid but spatially useless — the analyst decides per question. |