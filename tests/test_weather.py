from unittest.mock import MagicMock

import pytest

from src import weather


def valid_payload(year: int = 2024, month: int = 2) -> dict:
    hours = weather.expected_wall_clock_hours(year, month)
    size = len(hours)
    return {
        "timezone": weather.TIMEZONE,
        "latitude": weather.NYC_LAT,
        "longitude": weather.NYC_LON,
        "hourly_units": dict(weather.EXPECTED_HOURLY_UNITS),
        "hourly": {
            "time": hours.strftime("%Y-%m-%dT%H:%M").tolist(),
            "temperature_2m": [10.0] * size,
            "precipitation": [0.0] * size,
            "rain": [0.0] * size,
            "snowfall": [0.0] * size,
            "wind_speed_10m": [5.0] * size,
        },
    }


def test_valid_month_has_every_hour_and_missingness_flag():
    payload = valid_payload()
    payload["hourly"]["temperature_2m"][0] = None

    result = weather.process_weather_payload(payload, 2024, 2)

    assert len(result) == 696
    assert int(result["is_missing_observation"].sum()) == 1


def test_missing_hour_is_rejected():
    payload = valid_payload()
    for values in payload["hourly"].values():
        del values[-1]

    with pytest.raises(ValueError, match="Missing expected wall-clock hours"):
        weather.process_weather_payload(payload, 2024, 2)


def test_request_sets_explicit_units_timezone_and_time_format(monkeypatch):
    captured = {}
    response = MagicMock()
    response.json.return_value = valid_payload()

    def fake_get(_url, *, params, timeout):
        captured.update(params)
        assert timeout == 60
        return response

    monkeypatch.setattr(weather.requests, "get", fake_get)

    weather.fetch_weather_month(2024, 2)

    assert captured["timezone"] == "America/New_York"
    assert captured["temperature_unit"] == "celsius"
    assert captured["wind_speed_unit"] == "kmh"
    assert captured["precipitation_unit"] == "mm"
    assert captured["timeformat"] == "iso8601"


def test_invalid_payload_is_rejected_before_it_can_be_stored():
    invalid = {"hourly": {"time": ["invalid"] * 696}}

    with pytest.raises(ValueError, match="Weather validation failed"):
        weather.process_weather_payload(invalid, 2024, 2)


def test_raw_object_metadata_must_match_manifest_digest():
    digest = "a" * 64
    entry = {
        "raw_key": "raw/weather_hourly/weather_2024-02.json",
        "content_sha256": digest,
    }

    selected = weather.manifest_weather_digest(entry, entry["raw_key"])

    with pytest.raises(ValueError, match="differs from the manifest"):
        weather.validate_raw_weather_metadata({"sha256": "b" * 64}, selected)


def test_processed_weather_metadata_must_track_current_raw_and_transform():
    digest = "a" * 64
    metadata = {
        "source-weather-sha256": digest,
        "weather-transform-version": weather.WEATHER_TRANSFORM_VERSION,
    }

    assert weather.validate_processed_weather_metadata(metadata, digest) is None
    with pytest.raises(ValueError, match="different raw"):
        weather.validate_processed_weather_metadata(metadata, "b" * 64)
