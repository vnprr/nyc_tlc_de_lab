import logging
from numbers import Integral

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_dtype

# Bump this value whenever transformation logic or the processed schema changes.
# The manifest can use it alongside the raw object version to trigger reprocessing.
TRANSFORM_VERSION = "3.0.0"

# TLC timestamps describe New York wall-clock time without an offset.  Duration
# must therefore be calculated from timezone-aware instants, while the original
# naive timestamps remain the event-time and partitioning contract.
LOCAL_TIMEZONE = "America/New_York"

# EDA found legitimate records close to a month rollover, but much older dates
# were broken taximeter clocks. A fixed seven-day margin keeps those boundary
# records without making the output depend on the day when the job is rerun.
REPORTING_BOUNDARY_MARGIN = pd.Timedelta(days=7)

REJECTION_REASONS = (
    "missing_pickup_timestamp",
    "pickup_before_trusted_window",
    "pickup_after_trusted_window",
)

QUALITY_FLAGS = [
    "is_flex_fare_record",
    "is_unknown_ratecode",
    "is_negative_transaction",
    "is_amount_sign_mismatch",
    "is_exact_duplicate",
    "is_outside_reporting_month",
    "is_missing_dropoff",
    "is_ambiguous_pickup_datetime",
    "is_nonexistent_pickup_datetime",
    "is_ambiguous_dropoff_datetime",
    "is_nonexistent_dropoff_datetime",
    "is_nonpositive_duration",
    "is_long_duration",
    "is_near_24h_duration",
    "is_over_24h_duration",
    "is_negative_distance",
    "is_zero_distance",
    "is_extreme_distance",
    "is_implausible_speed",
    "is_missing_passenger_count",
    "is_negative_passenger_count",
    "is_zero_passengers",
    "is_high_passenger_count",
    "has_unknown_zone",
    "has_outside_nyc_zone",
]

RENAME = {
    "VendorID": "vendor_id",
    "tpep_pickup_datetime": "pickup_datetime",
    "tpep_dropoff_datetime": "dropoff_datetime",
    "RatecodeID": "ratecode_id",
    "PULocationID": "pu_location_id",
    "DOLocationID": "do_location_id",
    "Airport_fee": "airport_fee",
}

COMPONENT_COLS = [
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "congestion_surcharge",
    "airport_fee",
    "cbd_congestion_fee",
]


def _as_flag(values: pd.Series) -> pd.Series:
    """Return a quality flag with exactly two states and bool dtype."""
    return values.fillna(False).astype(bool)


def _validate_reporting_period(reporting_year: int, reporting_month: int) -> None:
    """Validate period arguments before constructing pandas timestamps."""
    if (
        isinstance(reporting_year, bool)
        or not isinstance(reporting_year, Integral)
        or not 1 <= reporting_year <= 9999
    ):
        raise ValueError("reporting_year must be an integer between 1 and 9999")

    if (
        isinstance(reporting_month, bool)
        or not isinstance(reporting_month, Integral)
        or not 1 <= reporting_month <= 12
    ):
        raise ValueError("reporting_month must be an integer between 1 and 12")


def _localize_wall_clock(
    values: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Map naive New York wall-clock values to UTC instants safely.

    A fall-back hour maps to two possible instants and a spring-forward hour
    maps to no instant.  Both cases become ``NaT`` instead of being guessed.
    The two probes distinguish those cases without changing the source values.
    """
    if not is_datetime64_dtype(values.dtype):
        raise TypeError("trip timestamps must have a naive datetime64 dtype")

    localized = values.dt.tz_localize(
        LOCAL_TIMEZONE,
        ambiguous="NaT",
        nonexistent="NaT",
    )
    nonexistent_probe = values.dt.tz_localize(
        LOCAL_TIMEZONE,
        ambiguous=False,
        nonexistent="NaT",
    )

    source_present = values.notna()
    nonexistent = _as_flag(source_present & nonexistent_probe.isna())
    ambiguous = _as_flag(source_present & localized.isna() & ~nonexistent)

    return localized.dt.tz_convert("UTC"), ambiguous, nonexistent


def transform_trips(
    df: pd.DataFrame,
    reporting_year: int,
    reporting_month: int,
    source_file: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split source rows into deterministic processed and rejected datasets.

    Trust is derived only from the source file's reporting period and the
    fixed EDA-backed boundary margin.
    """
    _validate_reporting_period(reporting_year, reporting_month)

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")
    if not isinstance(source_file, str) or not source_file.strip():
        raise ValueError("source_file must be a non-empty string")

    reporting_start = pd.Timestamp(
        year=reporting_year,
        month=reporting_month,
        day=1,
    )

    reporting_end = reporting_start + pd.DateOffset(months=1)
    trusted_start = reporting_start - REPORTING_BOUNDARY_MARGIN
    trusted_end = reporting_end + REPORTING_BOUNDARY_MARGIN

    source = df.copy()

    # The raw file is immutable, so its zero-based row position forms a stable
    # lineage key with source_file. Exact duplicates stay in the dataset and
    # both sides of every duplicate group are marked for explicit downstream
    # decisions. Calculate this before adding any technical columns.
    source["source_row_number"] = np.arange(len(source), dtype=np.int64)
    source["is_exact_duplicate"] = df.duplicated(keep=False).to_numpy(
        dtype=bool,
    )
    source["source_file"] = source_file

    # Schema v1 does not have the fee. Adding the neutral value gives both
    # source versions one stable processed schema.
    if "cbd_congestion_fee" not in source.columns:
        source["cbd_congestion_fee"] = 0.0

    source = source.rename(columns=RENAME)

    pickup = source["pickup_datetime"]

    missing_pickup = pickup.isna()
    before_trusted_window = pickup.lt(trusted_start)
    after_trusted_window = pickup.ge(trusted_end)
    rejected_mask = missing_pickup | before_trusted_window | after_trusted_window

    rejected = source.loc[rejected_mask].copy()
    rejected["rejection_reason"] = pd.Series(
        pd.NA,
        index=rejected.index,
        dtype="string",
    )
    rejected.loc[missing_pickup, "rejection_reason"] = "missing_pickup_timestamp"
    rejected.loc[before_trusted_window, "rejection_reason"] = "pickup_before_trusted_window"
    rejected.loc[after_trusted_window, "rejection_reason"] = "pickup_after_trusted_window"
    if rejected["rejection_reason"].isna().any():
        raise RuntimeError("Rejected trip row has no rejection reason")

    result = source.loc[~rejected_mask].copy()

    pickup = result["pickup_datetime"]
    dropoff = result["dropoff_datetime"]

    # Documented TLC categories.
    result["is_flex_fare_record"] = _as_flag(result["payment_type"].eq(0))
    result["is_unknown_ratecode"] = _as_flag(result["ratecode_id"].eq(99))

    # Monetary flags.
    negative_fare = result["fare_amount"] < 0
    negative_total = result["total_amount"] < 0

    result["is_negative_transaction"] = _as_flag(negative_total)
    result["is_amount_sign_mismatch"] = _as_flag(negative_fare != negative_total)

    # Reporting period.
    result["is_outside_reporting_month"] = _as_flag(
        ~pickup.between(
            reporting_start,
            reporting_end,
            inclusive="left",
        )
    )

    # Duration. Source timestamps are naive New York wall-clock values.  Keep
    # them unchanged for event partitioning, but calculate elapsed time between
    # UTC instants.  Ambiguous/nonexistent endpoints are never guessed.
    result["is_missing_dropoff"] = _as_flag(dropoff.isna())
    pickup_instant, pickup_ambiguous, pickup_nonexistent = _localize_wall_clock(pickup)
    dropoff_instant, dropoff_ambiguous, dropoff_nonexistent = _localize_wall_clock(dropoff)

    result["is_ambiguous_pickup_datetime"] = pickup_ambiguous
    result["is_nonexistent_pickup_datetime"] = pickup_nonexistent
    result["is_ambiguous_dropoff_datetime"] = dropoff_ambiguous
    result["is_nonexistent_dropoff_datetime"] = dropoff_nonexistent
    result["trip_duration_minutes"] = (dropoff_instant - pickup_instant).dt.total_seconds().div(60)

    duration = result["trip_duration_minutes"]

    result["is_nonpositive_duration"] = _as_flag(duration.le(0))
    result["is_long_duration"] = _as_flag(duration.gt(360) & duration.lt(1380))
    result["is_near_24h_duration"] = _as_flag(duration.ge(1380) & duration.lt(1440))
    result["is_over_24h_duration"] = _as_flag(duration.ge(1440))

    # Distance.
    distance = result["trip_distance"]

    result["is_negative_distance"] = _as_flag(distance.lt(0))
    result["is_zero_distance"] = _as_flag(distance.eq(0))
    result["is_extreme_distance"] = _as_flag(distance.gt(100))

    # Average speed is calculated only for usable inputs.
    valid_speed_input = _as_flag(duration.gt(0) & distance.ge(0))

    result["average_speed_mph"] = np.nan
    result.loc[
        valid_speed_input,
        "average_speed_mph",
    ] = distance.loc[valid_speed_input] / (duration.loc[valid_speed_input] / 60)

    result["is_implausible_speed"] = _as_flag(result["average_speed_mph"].gt(80))

    # Passenger count.
    result["is_missing_passenger_count"] = _as_flag(result["passenger_count"].isna())
    result["is_negative_passenger_count"] = _as_flag(result["passenger_count"].lt(0))
    result["is_zero_passengers"] = _as_flag(result["passenger_count"].eq(0))
    result["is_high_passenger_count"] = _as_flag(result["passenger_count"].gt(6))

    # Zone validation.
    result["has_unknown_zone"] = _as_flag(
        result["pu_location_id"].eq(264) | result["do_location_id"].eq(264)
    )
    result["has_outside_nyc_zone"] = _as_flag(
        result["pu_location_id"].eq(265) | result["do_location_id"].eq(265)
    )

    logging.info(
        "Trip transformation completed: %s processed, %s rejected",
        f"{len(result):,}",
        f"{len(rejected):,}",
    )

    return result, rejected


def create_quality_summary(
    processed_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    raw_row_count: int,
) -> pd.DataFrame:
    """Create quality metrics and enforce row-count reconciliation."""
    if (
        isinstance(raw_row_count, bool)
        or not isinstance(raw_row_count, Integral)
        or raw_row_count <= 0
    ):
        raise ValueError("raw_row_count must be a positive integer")

    output_row_count = len(processed_df) + len(rejected_df)

    if raw_row_count != output_row_count:
        raise ValueError(
            "Row count reconciliation failed: "
            f"raw={raw_row_count:,}, "
            f"processed={len(processed_df):,}, "
            f"rejected={len(rejected_df):,}"
        )

    missing_flags = set(QUALITY_FLAGS) - set(processed_df.columns)

    if missing_flags:
        raise ValueError(f"Missing quality flags: {sorted(missing_flags)}")

    metrics = {
        "raw_rows": raw_row_count,
        "processed_rows": len(processed_df),
        "rejected_rows": len(rejected_df),
    }
    if "rejection_reason" not in rejected_df.columns:
        raise ValueError("Rejected dataset is missing rejection_reason")
    unknown_reasons = set(rejected_df["rejection_reason"].dropna()) - set(REJECTION_REASONS)
    if unknown_reasons:
        raise ValueError(f"Unknown rejection reasons: {sorted(unknown_reasons)}")
    metrics.update(
        {
            f"rejection_{reason}": int(rejected_df["rejection_reason"].eq(reason).sum())
            for reason in REJECTION_REASONS
        }
    )
    metrics.update(processed_df[QUALITY_FLAGS].sum().astype("int64").to_dict())

    summary = pd.Series(metrics, name="value").to_frame()
    summary.index.name = "metric"
    summary["unit"] = "rows"
    summary["percentage_of_raw"] = summary["value"].div(raw_row_count).mul(100).round(4)

    # Vendor reconciliation metric (H4): early-warning monitor for fee
    # structure changes. Rows with any missing component are excluded
    # (min_count) instead of being zero-filled - complete rows only.
    components = processed_df[COMPONENT_COLS].sum(axis=1, min_count=len(COMPONENT_COLS))
    residual = (processed_df["total_amount"] - components).round(2)

    vendor_metrics: list[dict[str, object]] = []
    for vendor_id, vendor_residual in residual.groupby(processed_df["vendor_id"]):
        complete = vendor_residual.dropna()
        if complete.empty:
            continue
        vendor_metrics.extend(
            [
                {
                    "metric": f"vendor_{vendor_id}_rows_in_check",
                    "value": len(complete),
                    "unit": "rows",
                    "percentage_of_raw": round(len(complete) / raw_row_count * 100, 4),
                },
                {
                    "metric": f"vendor_{vendor_id}_median_residual_usd",
                    "value": complete.median(),
                    "unit": "usd",
                    "percentage_of_raw": pd.NA,
                },
                {
                    "metric": f"vendor_{vendor_id}_reconciled_pct",
                    "value": round(complete.abs().le(0.01).mean() * 100, 2),
                    "unit": "percent",
                    "percentage_of_raw": pd.NA,
                },
            ]
        )

    if vendor_metrics:
        vendor_summary = pd.DataFrame.from_records(vendor_metrics).set_index("metric")
        summary = pd.concat([summary, vendor_summary])

    return summary
