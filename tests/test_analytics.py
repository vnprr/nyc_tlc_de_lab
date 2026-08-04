import pandas as pd
import pytest

from src import weather
from src.analytics import (
    REPORTED_TIME_QUALITY_FLAGS,
    aggregate_trips_hourly,
    join_hourly_weather,
)


def trip(**updates) -> dict:
    row = {
        "pickup_datetime": pd.Timestamp("2024-01-15 12:05:00"),
        "dropoff_datetime": pd.Timestamp("2024-01-15 12:15:00"),
        "total_amount": 10.0,
        "trip_duration_minutes": 10.0,
        "trip_distance": 2.0,
        "average_speed_mph": 12.0,
        "is_missing_dropoff": False,
        "is_outside_reporting_month": False,
        "is_exact_duplicate": False,
    }
    row.update({flag: False for flag in REPORTED_TIME_QUALITY_FLAGS})
    row.update(updates)
    return row


def test_aggregation_keeps_additive_values_and_derives_average():
    trips = pd.DataFrame(
        [
            trip(),
            trip(
                pickup_datetime=pd.Timestamp("2024-01-15 12:25:00"),
                total_amount=20.0,
                trip_duration_minutes=20.0,
                trip_distance=6.0,
                average_speed_mph=18.0,
            ),
        ]
    )

    row = aggregate_trips_hourly(trips, 2024, 1).iloc[0]

    assert row["trip_record_count"] == 2
    assert row["total_amount_sum"] == 30.0
    assert row["duration_minutes_sum"] == 30.0
    assert row["duration_minutes_count"] == 2
    assert row["avg_duration_min"] == 15.0


def test_flagged_trip_is_counted_but_excluded_from_time_metrics():
    trips = pd.DataFrame(
        [
            trip(
                trip_duration_minutes=400.0,
                average_speed_mph=0.3,
                is_long_duration=True,
            )
        ]
    )

    row = aggregate_trips_hourly(trips, 2024, 1).iloc[0]

    assert row["trip_record_count"] == 1
    assert row["time_flagged_count"] == 1
    assert row["valid_time_count"] == 0


def test_record_outside_physical_partition_fails():
    trips = pd.DataFrame(
        [
            trip(),
            trip(pickup_datetime=pd.Timestamp("2023-12-31 23:59:00")),
        ]
    )

    with pytest.raises(ValueError, match="outside expected period 2024-01"):
        aggregate_trips_hourly(trips, 2024, 1)


def test_weather_null_is_not_mistaken_for_missing_join_key():
    hours = weather.expected_wall_clock_hours(2024, 1)
    values = [0.0] * len(hours)
    weather_frame = pd.DataFrame(
        {
            "observed_hour": hours,
            "temperature_c": [None, *values[1:]],
            "precipitation_mm": values,
            "rain_mm": values,
            "snowfall_cm": values,
            "wind_speed_kmh": values,
            "is_missing_observation": [True, *([False] * (len(hours) - 1))],
        }
    )
    hourly_trips = pd.DataFrame({"pickup_hour": [hours[0]], "trip_record_count": [1]})

    result = join_hourly_weather(hourly_trips, weather_frame, 2024, 1)

    assert len(result) == 1
    assert pd.isna(result.loc[0, "temperature_c"])
