# Data Cleaning Decisions

The detailed analysis is available in `eda_yellow_trip_data.ipynb`.  
This file contains only the final cleaning decisions.


| Case                                                                                        | Decision                                                                         | Flag                                                                 | Definition                          |
| ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------- |
| Flex Fare records with missing values                                                       | Keep the records and preserve missing values. Do not fill them with zeros        | `is_flex_fare_record`                                                | `payment_type == 0`                 |
| Valid TLC codes such as `VendorID = 6` and `RatecodeID = 99zone`                            | Keep them unchanged                                                              | `is_unknown_ratecode` for rate code 99                               | `RatecodeID == 99`                  |
| Location IDs 264 and 265                                                                    | Keep them. Their meaning requires the separate Taxi Zones reference              | `is_unknown_zone`                                                    | `PU∈{264,265} or DO∈{264,265}`      |
| Negative transaction amounts                                                                | Keep the original signs. Do not convert them to positive values.                 | `is_negative_transaction`                                            | `total_amount < 0`                  |
| Fare and total have different signs                                                         | Keep the record and mark it for review.                                          | `is_amount_sign_mismatch`                                            | `(fare<0) != (total<0)`             |
| Duration is zero or negative                                                                | Keep the record, but exclude it from normal duration and speed analysis.         | `is_nonpositive_duration`                                            | `duration ≤ 0`                      |
| Duration is 6 to 24 hours                                                                   | Keep the record, but exclude it from normal duration and speed analysis.         | `is_long_duration`                                                   | `6h < duration < 23h`               |
| Duration is 23 to near 24 hours                                                             | Keep the record, but exclude it from normal duration and speed analysis.         | `is_near_24h_duration`                                               | `1380 ≤ duration < 1440`            |
| Duration is over 24 hours                                                                   | Keep the record, but exclude it from normal duration and speed analysis.         | `is_over_24h_duration`                                               | `duration ≥ 24h`                    |
| Pickup outside January 2024                                                                 | Keep the record, but exclude it from the January dataset.                        | `is_outside_reporting_month`                                         | `OR pickup ≥ first_day(next_month)` |
| Pickup timestamp is missing, older than the trusted range or later than the processing time | Move the record to `rejected`. Keep the original row and add a rejection reason. | `rejection_reason`                                                   | \-                                  |
| Distance is negative                                                                        | Keep the record. Zero distance alone does not prove that the trip is invalid.    | `is_negative_distance`                                               | `distance < 0`                      |
| Distance is zero                                                                            | Keep the record. Zero distance alone does not prove that the trip is invalid.    | `is_zero_distance`                                                   | `distance == 0`                     |
| Distance is greater than 100 miles                                                          | Keep the source value, but exclude it from normal trip analysis.                 | `is_extreme_distance`                                                | `distance > 100`                    |
| Average speed is greater than 80 mph                                                        | Keep the record, but exclude it from normal trip analysis.                       | `is_implausible_speed`                                               | `speed > 80`;                       |
| Passenger count is zero or greater than six                                                 | Keep the record. The TLC dictionary does not define these values as invalid.     | Optional `is_zero_passengers`<br><br>Excludes `passeger_count == NA` | `passenger_count == 0`              |
| Total does not match a simple sum of amount columns                                         | Keep the record. The amount structure differs between vendors.                   | No general error flag                                                | -                                   |
| Duplicate rows                                                                              | No duplicates were found.                                                        | No flag                                                              | \-                                  |


## Output

*   `raw` keeps the original file unchanged;
*   `processed` keeps accepted rows and adds quality flags;
*   `rejected` keeps rows that violate the trusted pickup timestamp rule;
*   every output row includes `source_file`;
*   the pipeline checks that `raw rows = processed rows + rejected rows`;
*   filtered datasets are created later for specific analyses.