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

# Hypothesis

## Missing values: 140162

Five different columns have identical amount of missing values. 
This is no coincidence. An identical numbr means there should be some pattern of missing values. 

## Dates from different months

`[np.int32(2002), np.int32(2009), np.int32(2023), np.int32(2024)]`

There are two different problems here.

### 1. Late arriving data

For dates like `2023-12-31 23:xx`, or `2024-02-01 00:01`. 
This can be correct data that arrived at the wrong time.

### 2. Fares from old times

This is broken taximeter.

## A massive number of negative amounts

1.3% of all trips have a negative `fare_amount`.

My hypothesis: these are refunds or payment adjustments. 
Based on 
[TLC data dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf).

`payment_type` labels:

```
0 = Flex Fare trip
1 = Credit cards
2 = Cash
3 = No charge
4 = Dispute
5 = Unknown
6 = Voided trip
```

## Max trip distance
`max trip_distance = 312,722 miles`. This is 12 times around Earth.

But there are only 59 trips longer than 100 miles out of 3 mln. 
Most likely its broken taximeter.

## Zero duplicates

TLC possibly removes them before delivering dataset.