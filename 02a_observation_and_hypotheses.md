# Console output

**Code file**: `02_profile_dirt.py`

```zsh
**************************************************
File: data/raw_download/yellow_tripdata_2024-01.parquet
**************************************************

Rows: 2,964,624, Columns: 19

--- COLUMNS & DTYPES ---
VendorID                          int32
tpep_pickup_datetime     datetime64[us]
tpep_dropoff_datetime    datetime64[us]
passenger_count                 float64
trip_distance                   float64
RatecodeID                      float64
store_and_fwd_flag                  str
PULocationID                      int32
DOLocationID                      int32
payment_type                      int64
fare_amount                     float64
extra                           float64
mta_tax                         float64
tip_amount                      float64
tolls_amount                    float64
improvement_surcharge           float64
total_amount                    float64
congestion_surcharge            float64
Airport_fee                     float64
dtype: object

--- MISSING VALUES ---
passenger_count         140162
RatecodeID              140162
store_and_fwd_flag      140162
congestion_surcharge    140162
Airport_fee             140162
dtype: int64

--- DIRTY DATA ---

--- I. Taxi trips outside 2024-01: ---
Expected year: 2024, Expected month: 1
Number of trips outside 2024-01: 18
Min pickup time: 2002-12-31 22:59:39, Max pickup time: 2024-02-01 00:01:15
Sample years: [np.int32(2002), np.int32(2009), np.int32(2023), np.int32(2024)]

--- II. Dropoff before pickup (timetravel) ---
Dirty rows: 56

--- III. Negative amounts ---
fare_amount          negative: 37,448/2,964,624,  min: -899.0
total_amount         negative: 35,504/2,964,624,  min: -900.0
tip_amount           negative: 102/2,964,624,  min: -80.0

--- IV. Distance 0 or absurd ---
trip_distance == 0:     60,371
trip_distance > 100 mi: 59
max trip_distance:      312722.3

--- V. Passenger count ---
passenger_count
0.0      31465
1.0    2188739
2.0     405103
3.0      91262
4.0      51974
5.0      33506
6.0      22353
7.0          8
8.0         51
9.0          1
NaN     140162
Name: count, dtype: int64

--- VI. Speed (distance / time) ---
Trips faster than 80 mph: 1,107
Max speed: 1443334 mph

--- VII. Duplicates ---
Amount of duplicates: 0
```

# Hypotheses

## H1. Rows with missing data

Rows with missing data are the same.

Five different columns have identical amount of missing values. 

This is no coincidence. An identical count suggests these are the same rows and there should be some pattern of missing values. 

Test: 

- `isna().all(axis=1) == 140 162`?
- Who is providing this data? Check `VendorID`

## H2. The core of negative amounts 

The core set of negative amounts are cancellations/returns

Negative amounts do not represent a single population. 

The core set `fare<0 AND total<0` consists of cancellations/returns so `payment_type` should be concentrated in: `no_charge`/`dispute`/`voided`.

Test: 

- Set intersections + distribution of `payment_type` per population vs. the total.

## H3. Negative tip

When only the tip is negtive these are corrections to the tips paid by card.

Test:

- Is the `payment_type` for this micro-population `credit_card` in around 100%?

## H4. Total amount

According to official dictionary: `total_amount` equals the sum of components with toleration to 1 cent.

Test: 

- scale and amount of diffrences

## H5. Labels consistency in code columns

The code columns contain only values that match labels from the official dictionary.

Test: 

- `unique()` vs. the dictionary for `payment_type`, `VendorID`, and `RatecodeID`.

## H6. Courses with unknown location

Some courses have an unknown location encoded by sentinels 264/265.

Test: 

- the number of `PU/DO` in ${264,\ 265}$ + values outside the range $1–265$.

## H7. Labels consistency in `store_and_fwd_flag`

Test:

- `store_and_fwd_flag` contains only `{Y, N}`.

## H8. Courses longer than 24h

There are courses longer than 24h because of not turned off taximeter.

## H9. Dates from different months

Year values `[np.int32(2002), np.int32(2009), np.int32(2023), np.int32(2024)]`

### H9a. Late arriving data

For dates like `2023-12-31 23:xx`, or `2024-02-01 00:01`. 

This can be correct data that arrived at the wrong time.

Test:

- 

### H9b. Fares from old times

This is broken taximeter.

Test: 

- 

## H9. Dates outside the file's month

The 18 out-of-period rows are NOT one phenomenon. They split into two populations:

### H9a. Late-arriving data (boundary rows)
Rows like `2023-12-31 23:xx` or `2024-02-01 00:01` are correct trips that
started at the month boundary and were assigned to the file by booking time.

Test:
- count rows with pickup in [2023-12-25, 2024-01-01) or [2024-02-01, 2024-02-08)
  (one week around the boundary) → expected: nearly all of the 18

### H9b. Broken taximeter clock (ancient dates)
Rows from 2002/2009 come from devices with a reset clock. The pickup date
is our future partition key, so these rows cannot be trusted or placed.

Test:
- count rows with pickup < 2023-01-01 or > today → expected: a handful
- sanity check: H9a count + H9b count == 18 (no third population hiding)

# Observations (already measured, no further test needed)

## O1. Extreme trip_distance values are isolated device errors
max = 312,722 mi (~12x Earth's circumference), but only 59 rows > 100 mi
out of 2.96M. Isolated absurd magnitudes = device/entry errors, not a data
segment. Consequence: mean() on this column is useless until flagged.

## O2. Zero duplicate rows
TLC deduplicates before publishing. Our pipeline will still guard against
duplicates from Day 4 on, because re-running ingestion is where duplicates
are usually born - in the pipeline, not in the source.