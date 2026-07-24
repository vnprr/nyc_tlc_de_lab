# Data Cleaning Decisions

The detailed analysis is available in `eda_yellow_trip_data.ipynb`.
This file contains only the final cleaning decisions.

| Case | Decision | Flag |
| --- | --- | --- |
| Flex Fare records with missing values | Keep the records and preserve missing values. Do not fill them with zero. | `is_flex_fare_record` |
| Valid TLC codes such as `VendorID = 6` and `RatecodeID = 99` | Keep them unchanged. | `is_unknown_ratecode` for rate code 99 |
| Negative transaction amounts | Keep the original signs. Do not convert them to positive values. | `is_negative_transaction` |
| Fare and total have different signs | Keep the record and mark it for review. | `has_amount_sign_mismatch` |
| Total does not match a simple sum of amount columns | Keep the record. The amount structure differs between vendors. | No general error flag |
| Pickup outside January 2024 | Keep the record, but exclude it from the January dataset. | `is_outside_reporting_month` |
| Pickup timestamp is missing, older than the trusted range or later than the processing time | Move the record to `rejected`. Keep the original row and add a rejection reason. | `rejection_reason` |
| Duration is zero, negative or close to 24 hours | Keep the record, but exclude it from normal duration and speed analysis. | `has_nonpositive_duration`, `has_near_24h_duration` |
| Distance is zero | Keep the record. Zero distance alone does not prove that the trip is invalid. | `has_zero_distance` |
| Distance is greater than 100 miles | Keep the source value, but exclude it from normal trip analysis. | `has_extreme_distance` |
| Average speed is greater than 80 mph | Keep the record, but exclude it from normal trip analysis. | `has_implausible_speed` |
| Passenger count is zero or greater than six | Keep the record. The TLC dictionary does not define these values as invalid. | Optional `has_zero_passengers` |
| Location IDs 264 and 265 | Keep them. Their meaning requires the separate Taxi Zones reference. | No error flag |
| Duplicate rows | No duplicates were found, so do not use `drop_duplicates()`. | No flag |

## Output

- `raw` keeps the original file unchanged;
- `processed` keeps accepted rows and adds quality flags;
- `rejected` keeps rows that violate the trusted pickup timestamp rule;
- every output row includes `source_file`;
- the pipeline checks that `raw rows = processed rows + rejected rows`;
- filtered datasets are created later for specific analyses.
