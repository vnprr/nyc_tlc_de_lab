"""Open-Meteo ingestion and validation for NYC hourly weather.

Time contract
-------------
Open-Meteo is requested with ``timezone=America/New_York``, but the returned
hour labels do not contain a UTC offset or a DST ``fold`` marker.  Therefore
this module deliberately stores *naive local wall-clock labels* and expects
exactly one row for every nominal label from 00:00 through 23:00.

That is compatible with the current taxi data, which is also timestamped as
naive local time, but it is not a lossless representation of physical time:
the nonexistent spring-forward hour is still present in Open-Meteo data and
the two fall-back occurrences of the repeated hour cannot be distinguished.
Moving the lake to UTC instants plus an explicit local-time dimension is the
proper future fix.  Until then, missing or duplicated wall-clock labels are
data-contract violations, not tolerated DST exceptions.
"""

from collections.abc import Mapping, Sequence
from numbers import Integral, Real

import numpy as np
import pandas as pd
import requests
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

API_URL = "https://archive-api.open-meteo.com/v1/archive"
NYC_LAT, NYC_LON = 40.7128, -74.006
WEATHER_TRANSFORM_VERSION = "1.0.0"
# Open-Meteo reports the coordinates of the selected model grid cell, not
# necessarily the exact requested point.  A small tolerance accepts that
# documented behaviour while rejecting a valid-looking response for another
# city or a default coordinate such as (0, 0).
MAX_COORDINATE_DELTA_DEGREES = 0.25
HOURLY_VARS = "temperature_2m,precipitation,rain,snowfall,wind_speed_10m"
TIMEZONE = "America/New_York"
EXPECTED_HOURLY_UNITS = {
    "time": "iso8601",
    "temperature_2m": "°C",
    "precipitation": "mm",
    "rain": "mm",
    "snowfall": "cm",
    "wind_speed_10m": "km/h",
}

RENAME = {
    "time": "observed_hour",
    "temperature_2m": "temperature_c",
    "precipitation": "precipitation_mm",
    "rain": "rain_mm",
    "snowfall": "snowfall_cm",
    "wind_speed_10m": "wind_speed_kmh",
}
VALUE_COLS = [
    "temperature_c",
    "precipitation_mm",
    "rain_mm",
    "snowfall_cm",
    "wind_speed_kmh",
]
PROCESSED_WEATHER_COLUMNS = [
    "observed_hour",
    *VALUE_COLS,
    "is_missing_observation",
]
NONNEGATIVE_VALUE_COLS = [
    "precipitation_mm",
    "rain_mm",
    "snowfall_cm",
    "wind_speed_kmh",
]


def manifest_weather_digest(entry: object, expected_raw_key: str) -> str:
    """Return the selected raw digest from a small weather manifest entry."""
    if not isinstance(entry, Mapping) or entry.get("raw_key") != expected_raw_key:
        raise ValueError(f"No current raw weather manifest entry for {expected_raw_key}")
    digest = entry.get("content_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest.lower())
    ):
        raise ValueError(f"Invalid raw weather SHA-256 for {expected_raw_key}")
    return digest.lower()


def validate_raw_weather_metadata(metadata: object, expected_digest: str) -> None:
    """Prove that a fixed raw key still contains the manifest-selected bytes."""
    if not isinstance(metadata, Mapping):
        raise ValueError("Raw weather object has no metadata")
    observed = str(metadata.get("sha256", "")).lower()
    if observed != expected_digest:
        raise ValueError("Raw weather metadata SHA-256 differs from the manifest")


def validate_processed_weather_metadata(metadata: object, source_digest: str) -> None:
    """Prove that processed weather was built from the selected raw version."""
    if not isinstance(metadata, Mapping):
        raise ValueError("Processed weather object has no metadata")
    normalized = {str(key).lower(): str(value) for key, value in metadata.items()}
    if normalized.get("source-weather-sha256", "").lower() != source_digest:
        raise ValueError("Processed weather was built from a different raw object")
    if normalized.get("weather-transform-version") != WEATHER_TRANSFORM_VERSION:
        raise ValueError("Processed weather uses an outdated transform version")


def _month_bounds(year: int, month: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    if (
        isinstance(year, bool)
        or not isinstance(year, Integral)
        or isinstance(month, bool)
        or not isinstance(month, Integral)
        or not 1 <= month <= 12
    ):
        raise ValueError("year and month must identify a valid calendar month")

    try:
        start = pd.Timestamp(year=int(year), month=int(month), day=1)
        end = start + pd.DateOffset(months=1)
    except (OverflowError, ValueError) as exc:
        raise ValueError("year and month must identify a valid calendar month") from exc
    return start, end


def expected_wall_clock_hours(year: int, month: int) -> pd.DatetimeIndex:
    """Return the nominal, naive local-hour labels required for a month.

    The index intentionally has ``days_in_month * 24`` entries even in DST
    transition months.  See the module-level time contract before using this
    as a representation of elapsed physical time.
    """

    start, end = _month_bounds(year, month)
    return pd.date_range(start=start, end=end, inclusive="left", freq="h")


def fetch_weather_month(year: int, month: int) -> dict:
    """Fetch one fully completed calendar month from Open-Meteo."""

    start, end_exclusive = _month_bounds(year, month)
    today_in_new_york = pd.Timestamp.now(tz=TIMEZONE).normalize().tz_localize(None)
    if end_exclusive > today_in_new_york:
        raise ValueError(
            f"Month {year}-{month:02d} has not fully ended; refusing to ingest a partial month."
        )

    response = requests.get(
        API_URL,
        params={
            "latitude": NYC_LAT,
            "longitude": NYC_LON,
            "start_date": start.date().isoformat(),
            "end_date": (end_exclusive - pd.Timedelta(days=1)).date().isoformat(),
            "hourly": HOURLY_VARS,
            "timezone": TIMEZONE,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "timeformat": "iso8601",
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise ValueError("Open-Meteo response must be a JSON object")
    if payload.get("error"):
        raise ValueError(f"Open-Meteo error: {payload.get('reason')}")
    if "hourly" not in payload:
        raise ValueError("Open-Meteo response missing 'hourly' section")
    return dict(payload)


def _validate_payload_structure(payload: object) -> Mapping[str, Sequence[object]]:
    """Validate the JSON shape before constructing a DataFrame from it."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        raise ValueError("Weather validation failed:\n- Payload must be a JSON object")

    if payload.get("timezone") != TIMEZONE:
        errors.append(f"timezone must be {TIMEZONE!r}, got {payload.get('timezone')!r}")

    for field, expected in (("latitude", NYC_LAT), ("longitude", NYC_LON)):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, Real) or not np.isfinite(value):
            errors.append(f"{field} must be a finite numeric coordinate")
        elif abs(float(value) - expected) > MAX_COORDINATE_DELTA_DEGREES:
            errors.append(
                f"{field} is outside the accepted NYC grid tolerance: "
                f"expected approximately {expected}, got {value}"
            )

    hourly_units = payload.get("hourly_units")
    if not isinstance(hourly_units, Mapping):
        errors.append("'hourly_units' must be a JSON object")
    else:
        missing_units = set(EXPECTED_HOURLY_UNITS) - set(hourly_units)
        unexpected_units = set(hourly_units) - set(EXPECTED_HOURLY_UNITS)
        if missing_units:
            errors.append(f"Missing hourly unit fields: {sorted(missing_units)}")
        if unexpected_units:
            errors.append(f"Unexpected hourly unit fields: {sorted(unexpected_units)}")
        for column, expected_unit in EXPECTED_HOURLY_UNITS.items():
            if column in hourly_units and hourly_units[column] != expected_unit:
                errors.append(
                    f"hourly_units.{column} must be {expected_unit!r}, got {hourly_units[column]!r}"
                )

    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        errors.append("'hourly' must be a JSON object")
        raise ValueError("Weather validation failed:\n- " + "\n- ".join(errors))

    missing = set(RENAME) - set(hourly)
    unexpected = set(hourly) - set(RENAME)
    if missing:
        errors.append(f"Missing hourly fields: {sorted(missing)}")
    if unexpected:
        errors.append(f"Unexpected hourly fields: {sorted(unexpected)}")

    lengths: dict[str, int] = {}
    for column in sorted(set(RENAME) & set(hourly)):
        values = hourly[column]
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            errors.append(f"hourly.{column} must be an array")
            continue
        lengths[column] = len(values)

    if lengths and len(set(lengths.values())) != 1:
        details = ", ".join(f"{name}={size}" for name, size in lengths.items())
        errors.append(f"Hourly arrays have different lengths: {details}")

    for source_column in set(RENAME) - {"time"}:
        values = hourly.get(source_column)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            continue
        invalid_positions = [
            index
            for index, value in enumerate(values)
            if value is not None and (isinstance(value, bool) or not isinstance(value, Real))
        ]
        if invalid_positions:
            errors.append(
                f"hourly.{source_column} contains non-numeric values at "
                f"positions {invalid_positions[:5]}"
            )

    if errors:
        raise ValueError("Weather validation failed:\n- " + "\n- ".join(errors))
    return hourly


def _summarize_hours(hours: pd.DatetimeIndex, limit: int = 5) -> str:
    labels = [timestamp.isoformat() for timestamp in hours[:limit]]
    suffix = " ..." if len(hours) > limit else ""
    return ", ".join(labels) + suffix


def validate_processed_weather(
    df: pd.DataFrame,
    year: int,
    month: int,
) -> None:
    """Enforce the processed-weather schema and monthly key completeness."""

    expected = expected_wall_clock_hours(year, month)
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    errors: list[str] = []
    missing_columns = set(PROCESSED_WEATHER_COLUMNS) - set(df.columns)
    unexpected_columns = set(df.columns) - set(PROCESSED_WEATHER_COLUMNS)
    if missing_columns:
        errors.append(f"Missing columns: {sorted(missing_columns)}")
    if unexpected_columns:
        errors.append(f"Unexpected columns: {sorted(unexpected_columns)}")
    if errors:
        raise ValueError("Weather validation failed:\n- " + "\n- ".join(errors))

    observed = df["observed_hour"]
    observed_is_datetime = is_datetime64_any_dtype(observed.dtype)
    if not observed_is_datetime:
        errors.append("observed_hour must have a datetime dtype")
    elif isinstance(observed.dtype, pd.DatetimeTZDtype):
        errors.append(
            "observed_hour must contain naive local wall-clock labels; "
            "timezone-aware values do not match the current lake contract"
        )
    else:
        if observed.isna().any():
            errors.append("observed_hour contains null values")
        if (observed != observed.dt.floor("h")).any():
            errors.append("observed_hour contains values not aligned to a full hour")

        duplicate_mask = observed.duplicated(keep=False)
        if duplicate_mask.any():
            duplicates = pd.DatetimeIndex(observed.loc[duplicate_mask].unique()).sort_values()
            errors.append(
                f"Duplicated wall-clock hours ({len(duplicates)} unique): "
                f"{_summarize_hours(duplicates)}"
            )

        actual = pd.DatetimeIndex(observed.dropna().unique()).sort_values()
        missing_hours = expected.difference(actual)
        unexpected_hours = actual.difference(expected)
        if len(missing_hours):
            errors.append(
                f"Missing expected wall-clock hours ({len(missing_hours)}): "
                f"{_summarize_hours(missing_hours)}"
            )
        if len(unexpected_hours):
            errors.append(
                f"Unexpected wall-clock hours ({len(unexpected_hours)}): "
                f"{_summarize_hours(unexpected_hours)}"
            )

    for column in VALUE_COLS:
        if is_bool_dtype(df[column].dtype) or not is_numeric_dtype(df[column].dtype):
            errors.append(f"{column} must have a numeric dtype")
            continue
        values = df[column].dropna()
        if (~np.isfinite(values)).any():
            errors.append(f"{column} contains non-finite values")

    temperature = df["temperature_c"]
    if is_numeric_dtype(temperature.dtype):
        valid_temperature = temperature.dropna()
        if not valid_temperature.empty and (
            valid_temperature.lt(-30).any() or valid_temperature.gt(45).any()
        ):
            errors.append(
                "Temperature out of sanity range [-30, 45] C: "
                f"[{valid_temperature.min()}, {valid_temperature.max()}]"
            )

    for column in NONNEGATIVE_VALUE_COLS:
        if is_numeric_dtype(df[column].dtype) and df[column].dropna().lt(0).any():
            errors.append(f"Negative values in {column}")

    missing_flag = df["is_missing_observation"]
    if not is_bool_dtype(missing_flag.dtype) or missing_flag.isna().any():
        errors.append("is_missing_observation must be a non-null boolean column")
    else:
        expected_missing_flag = df[VALUE_COLS].isna().any(axis=1)
        if not missing_flag.astype(bool).equals(expected_missing_flag):
            errors.append("is_missing_observation is inconsistent with weather value nulls")

    if errors:
        raise ValueError("Weather validation failed:\n- " + "\n- ".join(errors))


def process_weather_payload(payload: dict, year: int, month: int) -> pd.DataFrame:
    """Convert and validate one raw Open-Meteo monthly payload."""

    _month_bounds(year, month)
    hourly = _validate_payload_structure(payload)
    frame = pd.DataFrame({target: hourly[source] for source, target in RENAME.items()})

    try:
        frame["observed_hour"] = pd.to_datetime(
            frame["observed_hour"],
            format="ISO8601",
            errors="raise",
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Weather validation failed:\n- observed_hour contains invalid timestamps"
        ) from exc

    for column in VALUE_COLS:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")

    frame["is_missing_observation"] = frame[VALUE_COLS].isna().any(axis=1)
    frame = frame[PROCESSED_WEATHER_COLUMNS].sort_values("observed_hour").reset_index(drop=True)
    validate_processed_weather(frame, year, month)
    return frame
