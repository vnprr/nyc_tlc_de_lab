from pathlib import Path
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)

FILE = Path("data/raw_download/yellow_tripdata_2024-01.parquet")
EXPECTED_YEAR = 2024
EXPECTED_MONTH = 1

df = pd.read_parquet(FILE)

print("*" * 50)
print(f"File: {FILE}")
print("*" * 50)
print(f"\nRows: {len(df):,}, Columns: {len(df.columns)}")

print(f"\n--- COLUMNS & DTYPES ---")
print(df.dtypes)

print(f"\n--- MISSING VALUES ---")
missing = df.isna().sum()
print(missing[missing > 0].sort_values(ascending=False))

print(f"\n--- DIRTY DATA ---")
print(f"\n--- I. Taxi trips outside {EXPECTED_YEAR}-{EXPECTED_MONTH:02d}: ---")
print(f"Expected year: {EXPECTED_YEAR}, Expected month: {EXPECTED_MONTH}")
pickup = df['tpep_pickup_datetime']
outside = pickup[(pickup.dt.year != EXPECTED_YEAR) | (pickup.dt.month != EXPECTED_MONTH)]
print(f"Number of trips outside {EXPECTED_YEAR}-{EXPECTED_MONTH:02d}: {len(outside):,}")
print(f"Min pickup time: {min(outside)}, Max pickup time: {max(outside)}")
if len(outside) > 0:
    print(f"Sample years:", sorted(outside.dt.year.unique()))

print("\n--- II. Dropoff before pickup (timetravel) ---")
negative_duration = df[df['tpep_dropoff_datetime'] < df['tpep_pickup_datetime']]
print(f"Dirty rows: {len(negative_duration):,}")

print("\n--- III. Negative amounts ---")
for col in ["fare_amount", "total_amount", "tip_amount"]:
    n = (df[col] < 0).sum()
    print(f"{col:<20} negative: {n:,}/{len(df):,},  min: {df[col].min()}")

print("\n--- IV. Distance 0 or absurd ---")
print(f"trip_distance == 0:     {(df['trip_distance'] == 0).sum():,}")
print(f"trip_distance > 100 mi: {(df['trip_distance'] > 100).sum():,}")
print(f"max trip_distance:      {df['trip_distance'].max()}")

print("\n--- V. Passenger count ---")
print(df["passenger_count"].value_counts(dropna=False).sort_index())

print("\n--- VI. Speed (distance / time) ---")
duration_h = (df["tpep_dropoff_datetime"] - df["tpep_pickup_datetime"]).dt.total_seconds() / 3600
valid = duration_h > 0
speed = df.loc[valid, "trip_distance"] / duration_h[valid]
print(f"Trips faster than 80 mph: {(speed > 80).sum():,}")
print(f"Max speed: {speed.max():.0f} mph")

print("\n--- VII. Duplicates ---")
print(f"Amount of duplicates: {df.duplicated().sum():,}")