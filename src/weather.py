"""Open-Meteo ingestion and processing for NYC hourly weather."""
import logging

import pandas as pd
import requests

API_URL = "https://archive-api.open-meteo.com/v1/archive"
NYC_LAT, NYC_LON = 40.7128, -74.006
HOURLY_VARS = "temperature_2m,precipitation,rain,snowfall,wind_speed_10m"
TIMEZONE = "America/New_York"

RENAME = {
    "time": "observed_hour",
    "temperature_2m": "temperature_c",
    "precipitation": "precipitation_mm",
    "rain": "rain_mm",
    "snowfall": "snowfall_cm",
    "wind_speed_10m": "wind_speed_kmh",
}
VALUE_COLS = ["temperature_c", "precipitation_mm", "rain_mm",
              "snowfall_cm", "wind_speed_kmh"]


def fetch_weather_month(year: int, month: int) -> dict:
    start = pd.Timestamp(year=year, month=month, day=1)
    end = start + pd.offsets.MonthEnd(0)
    if end >= pd.Timestamp.now():
        raise ValueError(
            f"Month {year}-{month:02d} has not fully ended; "
            "refusing to ingest a partial month."
        )
    response = requests.get(
        API_URL,
        params={
            "latitude": NYC_LAT, "longitude": NYC_LON,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "hourly": HOURLY_VARS, "timezone": TIMEZONE,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise ValueError(f"Open-Meteo error: {payload.get('reason')}")
    if "hourly" not in payload:
        raise ValueError("Open-Meteo response missing 'hourly' section")
    return payload


def process_weather_payload(payload: dict, year: int, month: int) -> pd.DataFrame:
    df = pd.DataFrame(payload["hourly"]).rename(columns=RENAME)
    df["observed_hour"] = pd.to_datetime(df["observed_hour"])

    errors = []
    missing_cols = ({"observed_hour", *VALUE_COLS}) - set(df.columns)
    if missing_cols:
        errors.append(f"Missing columns: {sorted(missing_cols)}")

    expected_hours = pd.Timestamp(year=year, month=month, day=1).days_in_month * 24
    if abs(len(df) - expected_hours) > 1:          # +/-1 tolerated for DST
        errors.append(f"Hour count {len(df)} vs expected {expected_hours}")
    elif len(df) != expected_hours:
        logging.warning("DST month detected: %d hours (expected %d)",
                        len(df), expected_hours)

    if not errors:
        temp = df["temperature_c"]
        if temp.min() < -30 or temp.max() > 45:
            errors.append(f"Temperature out of sanity range: "
                          f"[{temp.min()}, {temp.max()}]")
        for col in ["precipitation_mm", "rain_mm", "snowfall_cm",
                    "wind_speed_kmh"]:
            if (df[col].dropna() < 0).any():
                errors.append(f"Negative values in {col}")
        dupes = df["observed_hour"].duplicated().sum()
        if dupes > 1:
            errors.append(f"{dupes} duplicated hours (max 1 allowed for DST)")

    if errors:
        raise ValueError("Weather validation failed:\n- " + "\n- ".join(errors))

    df["is_missing_observation"] = df[VALUE_COLS].isna().any(axis=1)
    return df