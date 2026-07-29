"""
official TLC dictionary:
https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf
"""

from pathlib import Path
import pandas as pd

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

FILE = Path("data/raw_download/yellow_tripdata_2024-01.parquet")

PAYMENT_TYPES = {
    0: "flex_fare",
    1: "credit_card",
    2: "cash",
    3: "no_charge",
    4: "dispute",
    5: "unknown",
    6: "voided_trip",
}

VENDORS = {
    1: "creative_mobile",
    2: "curb_mobility",
    6: "myle",
    7: "helix",
}

RATECODES = {
    1: "standard",
    2: "jfk",
    3: "newark",
    4: "nassau_westchester",
    5: "negotiated",
    6: "group_ride",
    99: "null_unknown",
}

VALID_STORE_FWD = {"Y", "N"}

UNKNOWN_ZONES = {264, 265}  # sentinels: Unknown / Outside NYC
MAX_ZONE_ID = 265

MISSING_BLOCK = [
    "passenger_count",
    "RatecodeID",
    "store_and_fwd_flag",
    "congestion_surcharge",
    "Airport_fee",
]

df = pd.read_parquet(FILE)
n = len(df)
print(f"File: {FILE.name} | rows: {n:,}\n")


print("=" * 77)
print("H1: missing values block in 5 columns = one record segment")
print("=" * 77)
block_missing = df[MISSING_BLOCK].isna().all(axis=1)
print(f"Rows missing ALL 5 columns at once: {block_missing.sum():,}")
if block_missing.sum() == 140162:
    print("Confirmed. The missing values block is 140,162 rows long")
else:
    print("disconfirmed. The missing values block is not 140,162 rows long")

print("\nVendorID within the missing segment:")
print(df.loc[block_missing, "VendorID"].map(VENDORS).value_counts(dropna=False))
print("\nVendorID in the whole file:")
print(df["VendorID"].map(VENDORS).value_counts(dropna=False))


print("\n" + "=" * 77)
print("H2: negative amounts - population intersections and character")
print("=" * 77)
neg_fare = df["fare_amount"] < 0
neg_total = df["total_amount"] < 0
neg_tip = df["tip_amount"] < 0
print(f"fare<0 AND total<0 (core, reversals):   {(neg_fare & neg_total).sum():,}")
print(f"fare<0, total>=0 (mismatch):            {(neg_fare & ~neg_total).sum():,}")
print(f"fare>=0, total<0 (mismatch):            {(~neg_fare & neg_total).sum():,}")
print("\npayment_type for the core (fare<0 AND total<0):")
core = neg_fare & neg_total
print(df.loc[core, "payment_type"].map(PAYMENT_TYPES).value_counts())
print("\npayment_type for mismatches (fare<0 XOR total<0):")
mismatch = neg_fare ^ neg_total
print(df.loc[mismatch, "payment_type"].map(PAYMENT_TYPES).value_counts())
print("\npayment_type in the whole file (background, %):")
print((df["payment_type"].map(PAYMENT_TYPES).value_counts(normalize=True) * 100)
      .round(2))


print("\n" + "=" * 77)
print("H3: negative tip only = credit card tip corrections")
print("=" * 77)
only_neg_tip = neg_tip & ~neg_fare & ~neg_total
print(f"Count: {only_neg_tip.sum():,}")
print(df.loc[only_neg_tip, "payment_type"].map(PAYMENT_TYPES).value_counts())


print("\n" + "=" * 77)
print("H4: consistency total_amount = sum of components")
print("=" * 77)
components = (df["fare_amount"] + df["extra"] + df["mta_tax"]
              + df["tip_amount"] + df["tolls_amount"]
              + df["improvement_surcharge"]
              + df["congestion_surcharge"].fillna(0)
              + df["Airport_fee"].fillna(0))
diff = (df["total_amount"] - components).abs()
inconsistent = diff > 0.01  # 1-cent tolerance for float rounding errors
print(f"Inconsistent rows: {inconsistent.sum():,} ({inconsistent.mean()*100:.2f}%)")
if inconsistent.any():
    print("Distribution of the difference:")
    print(diff[inconsistent].describe())


print("\n" + "=" * 77)
print("H4 follow-up: what drives the 2.50 cluster?")
print("=" * 77)
signed_diff = df["total_amount"] - components   # NO abs: direction matters
print("Direction: total > components:", (signed_diff > 0.01).sum())
print("Direction: total < components:", (signed_diff < -0.01).sum())

print("\nOverlap with the missing-block segment (H1):")
print(f"inconsistent AND missing-block: {(inconsistent & block_missing).sum():,}")

print("\ncongestion_surcharge values among inconsistent rows:")
print(df.loc[inconsistent, "congestion_surcharge"]
      .value_counts(dropna=False).head())

print("\nextra values among inconsistent rows:")
print(df.loc[inconsistent, "extra"].value_counts().head())


print("\n" + "=" * 77)
print("H5: categorical codes vs the official dictionary")
print("=" * 77)
for col, valid in [("payment_type", PAYMENT_TYPES), ("VendorID", VENDORS),
                   ("RatecodeID", RATECODES)]:
    codes = df[col].dropna().unique()
    unknown = sorted(c for c in codes if c not in valid)
    status = "OK" if not unknown else f"OUTSIDE DICTIONARY: {unknown}"
    print(f"{col:<14} codes: {sorted(codes)}  ->  {status}")


print("\n" + "=" * 77)
print("H6: TLC zones - sentinels 264/265 and range check")
print("=" * 77)
for col in ["PULocationID", "DOLocationID"]:
    in_sentinel = df[col].isin(UNKNOWN_ZONES).sum()
    out_of_range = ((df[col] < 1) | (df[col] > MAX_ZONE_ID)).sum()
    print(f"{col}: unknown-zone (264/265): {in_sentinel:,} | "
          f"outside 1-{MAX_ZONE_ID}: {out_of_range:,}")
both_unknown = (df["PULocationID"].isin(UNKNOWN_ZONES)
                & df["DOLocationID"].isin(UNKNOWN_ZONES)).sum()
print(f"Both ends unknown: {both_unknown:,}")


print("\n" + "=" * 77)
print("H7: store_and_fwd_flag domain")
print("=" * 77)
values = df["store_and_fwd_flag"].dropna().unique()
outside = sorted(v for v in values if v not in VALID_STORE_FWD)
print(f"Values: {sorted(values)}  ->  "
      f"{'OK' if not outside else f'OUTSIDE {{Y,N}}: {outside}'}")


print("\n" + "=" * 77)
print("H8: trip duration > 24h (taximeter never turned off)")
print("=" * 77)
duration_h = (df["tpep_dropoff_datetime"]
              - df["tpep_pickup_datetime"]).dt.total_seconds() / 3600
print(f"Trips > 24h: {(duration_h > 24).sum():,}")
print(f"Trips > 6h:  {(duration_h > 6).sum():,}")
print(f"Max duration: {duration_h.max():.1f} h")


print("\n" + "=" * 77)
print("H9: splitting the 18 out-of-period rows into two populations")
print("=" * 77)
pickup = df["tpep_pickup_datetime"]

EXPECTED_START = pd.Timestamp("2024-01-01")
EXPECTED_END = pd.Timestamp("2024-02-01")          # exclusive: February is outside
BOUNDARY_MARGIN = pd.Timedelta(days=7)
ANCIENT_CUTOFF = pd.Timestamp("2023-01-01")
TODAY = pd.Timestamp.now()

outside = (pickup < EXPECTED_START) | (pickup >= EXPECTED_END)
print(f"All rows outside 2024-01: {outside.sum():,}")

# H9a: one week around the month boundaries
boundary = outside & (
    ((pickup >= EXPECTED_START - BOUNDARY_MARGIN) & (pickup < EXPECTED_START))
    | ((pickup >= EXPECTED_END) & (pickup < EXPECTED_END + BOUNDARY_MARGIN))
)
print(f"H9a boundary (late-arriving):       {boundary.sum():,}")

# H9b: untrustworthy dates (partition key cannot be trusted)
ancient = (pickup < ANCIENT_CUTOFF) | (pickup > TODAY)
print(f"H9b ancient/future (broken clock):  {ancient.sum():,}")

# closing check: do the subgroups exhaust the whole?
unexplained = outside & ~boundary & ~ancient
print(f"UNEXPLAINED (third population?):    {unexplained.sum():,}")
if unexplained.any():
    print(pickup[unexplained].sort_values())