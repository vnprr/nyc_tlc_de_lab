    """Build analytics/trips_weather_hourly: hourly trip aggregates joined
    with hourly weather. Reads processed partitions month by month."""
    import logging
    from pathlib import Path

    import pandas as pd

    from src.s3_io import download_file, list_keys, upload_df_overwrite

    BUCKET = "jakub-nyc-taxi-lake-2026"
    TAXI_PREFIX = "processed/yellow_taxi/"
    WEATHER_PREFIX = "processed/weather_hourly/"
    ANALYTICS_PREFIX = "analytics/trips_weather_hourly/"
    WORKDIR = Path("data/workdir")

    MONTHS = [(2024, 1), (2024, 2), (2024, 3), (2024, 4), (2025, 1)]

    EXCLUDE_FROM_TIME_METRICS = [
        "is_nonpositive_duration", "is_over_24h_duration", "is_implausible_speed",
    ]


    def read_partition(prefix: str, year: int, month: int) -> pd.DataFrame:
        part_prefix = f"{prefix}year={year}/month={month:02d}/"
        keys = list_keys(BUCKET, part_prefix, suffix=".parquet")
        frames = []
        for key in keys:
            local = WORKDIR / Path(key).name
            download_file(BUCKET, key, local)
            frames.append(pd.read_parquet(local))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)


    def build_month(year: int, month: int) -> None:
        df = read_partition(TAXI_PREFIX, year, month)
        if df.empty:
            logging.warning("No taxi partition for %d-%02d, skipping", year, month)
            return

        df["pickup_hour"] = df["pickup_datetime"].dt.floor("h")
        bad_time = df[EXCLUDE_FROM_TIME_METRICS].any(axis=1)

        base = df.groupby("pickup_hour").agg(
            trips_count=("pickup_datetime", "size"),
            avg_total_amount=("total_amount", "mean"),
        )
        clean = df.loc[~bad_time].groupby("pickup_hour").agg(
            avg_duration_min=("trip_duration_minutes", "mean"),
            avg_distance_mi=("trip_distance", "mean"),
            avg_speed_mph=("average_speed_mph", "mean"),
        )
        pct_flagged = (bad_time.groupby(df["pickup_hour"]).mean() * 100
                       ).rename("pct_time_flagged")
        hourly = base.join([clean, pct_flagged]).reset_index()

        weather = read_partition(WEATHER_PREFIX, year, month)
        result = hourly.merge(
            weather, left_on="pickup_hour", right_on="observed_hour", how="left",
        ).drop(columns=["observed_hour"])

        unmatched = int(result["temperature_c"].isna().sum())
        if unmatched:
            logging.warning("%d hours without weather match in %d-%02d",
                            unmatched, year, month)

        out_key = (f"{ANALYTICS_PREFIX}year={year}/month={month:02d}/"
                   f"trips_weather_{year}-{month:02d}.parquet")
        upload_df_overwrite(result, BUCKET, out_key, WORKDIR)


    if __name__ == "__main__":
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(message)s")
        for year, month in MONTHS:
            build_month(year, month)
        logging.info("Analytics build finished.")