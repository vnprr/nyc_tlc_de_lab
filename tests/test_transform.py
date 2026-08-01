import pandas as pd
import pytest

from src.transform import create_quality_summary, transform_trips

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

def test_boundary_trip_is_kept_and_flagged_outside_month():
    processed, rejected = run_transform(
        [{
            "tpep_pickup_datetime": pd.Timestamp("2023-12-31 23:50:00"),
            "tpep_dropoff_datetime": pd.Timestamp("2024-01-01 00:10:00"),
        }]
    )
    assert len(rejected) == 0
    assert bool(processed["is_outside_reporting_month"].iloc[0]) is True


def test_audit_processed_plus_rejected_equals_input():
    rows = [
        {},  # valid
        {"tpep_pickup_datetime": pd.Timestamp("2009-06-01 08:00:00")},  # reject
        {"trip_distance": 0.0},  # valid, flagged
        {"tpep_pickup_datetime": FROZEN_NOW + pd.Timedelta(days=1)},  # reject
    ]
    processed, rejected = run_transform(rows)
    assert len(processed) + len(rejected) == len(rows)


def test_missing_cbd_fee_is_added_as_zero():
    processed, _ = run_transform([{}])
    assert "cbd_congestion_fee" in processed.columns
    assert (processed["cbd_congestion_fee"] == 0.0).all()


def test_ratecode_sentinel_and_nan_handling():
    processed, _ = run_transform(
        [{"RatecodeID": 99.0}, {"RatecodeID": float("nan")}]
    )
    flags = processed["is_unknown_ratecode"]
    assert flags.dtype == bool          # never nullable, never <NA>
    assert bool(flags.iloc[0]) is True   # sentinel 99 -> flagged
    assert bool(flags.iloc[1]) is False  # missing is not the sentinel


def test_duration_flags_are_disjoint():
    def dropoff(minutes):
        return DEFAULT_ROW["tpep_pickup_datetime"] + pd.Timedelta(minutes=minutes)

    processed, _ = run_transform([
        {"tpep_dropoff_datetime": dropoff(30)},     # normal: no duration flag
        {"tpep_dropoff_datetime": dropoff(400)},    # long
        {"tpep_dropoff_datetime": dropoff(1400)},   # near 24h
        {"tpep_dropoff_datetime": dropoff(1500)},   # over 24h
    ])
    duration_flags = processed[[
        "is_nonpositive_duration", "is_long_duration",
        "is_near_24h_duration", "is_over_24h_duration",
    ]]
    # disjoint: no row may carry two duration flags at once
    assert (duration_flags.sum(axis=1) <= 1).all()
    assert duration_flags.sum(axis=1).tolist() == [0, 1, 1, 1]
    assert bool(processed["is_long_duration"].iloc[1]) is True
    assert bool(processed["is_near_24h_duration"].iloc[2]) is True
    assert bool(processed["is_over_24h_duration"].iloc[3]) is True


def test_quality_summary_raises_on_row_count_mismatch():
    processed, rejected = run_transform([{}])
    with pytest.raises(ValueError):
        create_quality_summary(
            processed, rejected, raw_row_count=len(processed) + 999,
        )