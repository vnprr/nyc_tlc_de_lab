from functions.transform_trips import (
    create_quality_summary,
    transform_trips,
)


processed_df = transform_trips(
    df,
    reporting_year=2024,
    reporting_month=1,
)

quality_summary = create_quality_summary(processed_df)

print(quality_summary)