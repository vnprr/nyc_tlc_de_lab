"""Unit tests for transform"""
import pandas as pd

from src.transform import transform_trips

FROZEN_NOW = pd.Timestamp("2024-02-15 10:00:00")

# test row with average values that wont be flagged
DEFAULT_ROW = {
    "VendorID": 2,
    "tpep_pickup_datetime": pd.Timestamp("2024-01-15 12:00:00"),
    "tpep_dropoff_datetime": pd.Timestamp("2024-01-15 12:20:00"),
    "passenger_count": 1.0,
    "trip_distance": 3.0,
    "RatecodeID": 1.0,
    "store_and_fwd_flag": "N",
    "PULocationID": 1,
    "DOLocationID": 2,
    "payment_type": 1,
    "fare_amount": 15.0,
    "extra": 1.0,
    "mta_tax": 0.5,
    "tip_amount": 3.0,
    "tolls_amount": 0.0,
    "improvement_surcharge": 1.0,
    "total_amount": 23.0,
    "congestion_surcharge": 2.5,
    "airport_fee": 0.0
}

# 01. 
# prepare a dataframe with default values
def make_source_df(rows: list[dict]) -> pd.DataFrame:
    """ 
    Prepare a dataframe with default values. 
    Overrides default values with the provided rows.
    """
    return pd.DataFrame(
        [{**DEFAULT_ROW, **row} for row in rows]
    )

# run transform on a list of rows
def run_transform(rows: list[dict]) -> pd.DataFrame:
    """Run transform on a list of rows"""
    df = make_source_df(rows)
    return transform_trips(
        df, 
        reporting_year=2024, 
        reporting_month=1, 
        source_file="test.parquet",
        processing_time=FROZEN_NOW
    )

# 02. TESTS
def test_ancient_pickup_is_rejected_with_reason():
    """Test: reject ancient pickup timestamps"""
    processed, rejected = run_transform(
        [{"tpep_pickup_datetime": pd.Timestamp("2002-12-31 23:00:00")}]
    )
    assert len(processed) == 0
    assert len(rejected) == 1
    assert rejected["rejection_reason"].iloc[0] == "untrustworthy_pickup_timestamp"

def test_future_pickup_is_rejected():
     """Test: reject future pickup timestamps"""
     processed, rejected = run_transform(
         [{"tpep_pickup_datetime": FROZEN_NOW + pd.Timedelta(days=3)}]
     )
     assert len(processed) == 0
     assert len(rejected) == 1

def test_boundary_trip_is_kept_and_flagged_outside_mont():
     """Test: reject trips outside the reporting month"""
     processed, rejected = run_transform(
         [{"tpep_pickup_datetime": pd.Timestamp("2024-02-01 00:00:00")}]
     )
     assert len(processed) == 1
     assert len(rejected) == 0