import numpy as np
import pandas as pd
import pytest

from src.validate import validate_source


def valid_source(*, cbd: bool = False) -> pd.DataFrame:
    row = {
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
    if cbd:
        row["cbd_congestion_fee"] = 0.75
    return pd.DataFrame([row])


@pytest.mark.parametrize(
    ("cbd", "year", "month"),
    [(False, 2024, 12), (True, 2025, 1)],
)
def test_period_uses_the_expected_schema_version(cbd, year, month):
    assert validate_source(valid_source(cbd=cbd), year, month) is None


def test_missing_or_unexpected_column_is_rejected():
    source = valid_source().drop(columns="fare_amount")
    source["unexpected"] = 1

    with pytest.raises(ValueError, match=r"missing columns.*fare_amount"):
        validate_source(source, 2024, 1)


@pytest.mark.parametrize("value", [np.inf, "not-a-number"])
def test_invalid_numeric_value_is_rejected(value):
    source = valid_source()
    source["total_amount"] = [value]

    with pytest.raises(ValueError, match="numeric"):
        validate_source(source, 2024, 1)
