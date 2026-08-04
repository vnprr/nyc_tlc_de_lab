import numpy as np
import pandas as pd
import pytest
from pandas.api.types import is_bool_dtype

from src.transform import QUALITY_FLAGS, create_quality_summary, transform_trips

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
    "Airport_fee": 0.0,
}


def make_source_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{**DEFAULT_ROW, **row} for row in rows])


def run_transform(
    rows: list[dict],
    *,
    year: int = 2024,
    month: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return transform_trips(
        make_source_df(rows),
        reporting_year=year,
        reporting_month=month,
        source_file=f"yellow_tripdata_{year:04d}-{month:02d}.parquet",
    )


def test_ancient_pickup_is_rejected_with_reason():
    processed, rejected = run_transform(
        [{"tpep_pickup_datetime": pd.Timestamp("2002-12-31 23:00:00")}]
    )

    assert processed.empty
    assert rejected["rejection_reason"].iloc[0] == "pickup_before_trusted_window"


def test_future_pickup_is_rejected():
    processed, rejected = run_transform(
        [{"tpep_pickup_datetime": pd.Timestamp("2024-02-08 00:00:00")}]
    )

    assert processed.empty
    assert rejected["rejection_reason"].iloc[0] == "pickup_after_trusted_window"


def test_boundary_trip_is_kept_and_flagged_outside_month():
    processed, rejected = run_transform(
        [
            {
                "tpep_pickup_datetime": pd.Timestamp("2023-12-31 23:50:00"),
                "tpep_dropoff_datetime": pd.Timestamp("2024-01-01 00:10:00"),
            }
        ]
    )

    assert rejected.empty
    assert bool(processed["is_outside_reporting_month"].iloc[0]) is True


def test_audit_processed_plus_rejected_equals_input():
    rows = [
        {},
        {"tpep_pickup_datetime": pd.Timestamp("2009-06-01 08:00:00")},
        {"trip_distance": 0.0},
        {"tpep_pickup_datetime": pd.Timestamp("2024-02-08 00:00:00")},
    ]

    processed, rejected = run_transform(rows)

    assert len(processed) + len(rejected) == len(rows)


def test_missing_cbd_fee_is_added_as_zero():
    processed, _ = run_transform([{}])

    assert "cbd_congestion_fee" in processed.columns
    assert (processed["cbd_congestion_fee"] == 0.0).all()


def test_ratecode_sentinel_and_nan_handling():
    processed, _ = run_transform([{"RatecodeID": 99.0}, {"RatecodeID": np.nan}])
    flags = processed["is_unknown_ratecode"]

    assert flags.dtype == bool
    assert bool(flags.iloc[0]) is True
    assert bool(flags.iloc[1]) is False


def test_duration_flags_are_disjoint():
    pickup = DEFAULT_ROW["tpep_pickup_datetime"]
    processed, _ = run_transform(
        [
            {"tpep_dropoff_datetime": pickup + pd.Timedelta(minutes=30)},
            {"tpep_dropoff_datetime": pickup + pd.Timedelta(minutes=400)},
            {"tpep_dropoff_datetime": pickup + pd.Timedelta(minutes=1400)},
            {"tpep_dropoff_datetime": pickup + pd.Timedelta(minutes=1500)},
        ]
    )
    duration_flags = processed[
        [
            "is_nonpositive_duration",
            "is_long_duration",
            "is_near_24h_duration",
            "is_over_24h_duration",
        ]
    ]

    assert (duration_flags.sum(axis=1) <= 1).all()
    assert duration_flags.sum(axis=1).tolist() == [0, 1, 1, 1]


def test_quality_summary_raises_on_row_count_mismatch():
    processed, rejected = run_transform([{}])

    with pytest.raises(ValueError, match="reconciliation failed"):
        create_quality_summary(processed, rejected, raw_row_count=len(processed) + 999)


def test_exact_duplicates_are_preserved_with_lineage():
    processed, _ = run_transform([{}, {}])

    assert len(processed) == 2
    assert processed["source_row_number"].tolist() == [0, 1]
    assert processed["is_exact_duplicate"].tolist() == [True, True]


def test_missing_dropoff_keeps_record_without_duration_or_speed():
    processed, _ = run_transform([{"tpep_dropoff_datetime": pd.NaT}])
    row = processed.iloc[0]

    assert bool(row["is_missing_dropoff"]) is True
    assert pd.isna(row["trip_duration_minutes"])
    assert pd.isna(row["average_speed_mph"])


def test_spring_forward_uses_real_elapsed_time():
    processed, _ = run_transform(
        [
            {
                "tpep_pickup_datetime": pd.Timestamp("2024-03-10 01:30:00"),
                "tpep_dropoff_datetime": pd.Timestamp("2024-03-10 03:30:00"),
            }
        ],
        month=3,
    )

    assert processed["trip_duration_minutes"].iloc[0] == 60.0


def test_fall_back_ambiguous_time_is_flagged_without_guessing():
    processed, _ = run_transform(
        [
            {
                "tpep_pickup_datetime": pd.Timestamp("2024-11-03 01:30:00"),
                "tpep_dropoff_datetime": pd.Timestamp("2024-11-03 02:30:00"),
            }
        ],
        month=11,
    )
    row = processed.iloc[0]

    assert bool(row["is_ambiguous_pickup_datetime"]) is True
    assert pd.isna(row["trip_duration_minutes"])
    assert pd.isna(row["average_speed_mph"])


def test_quality_flags_are_non_nullable_booleans():
    processed, _ = run_transform([{"passenger_count": np.nan, "tpep_dropoff_datetime": pd.NaT}])

    assert processed[QUALITY_FLAGS].isna().sum().sum() == 0
    assert all(is_bool_dtype(dtype) for dtype in processed[QUALITY_FLAGS].dtypes)


def test_unknown_and_outside_nyc_zones_are_distinct():
    processed, _ = run_transform([{"PULocationID": 264}, {"PULocationID": 265}])

    assert processed["has_unknown_zone"].tolist() == [True, False]
    assert processed["has_outside_nyc_zone"].tolist() == [False, True]
