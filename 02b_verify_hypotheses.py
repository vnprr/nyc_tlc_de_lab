from pathlib import Path
import pandas as pd

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

FILE = Path("data/raw_download/yellow_tripdata_2024-01.parquet")
df = pd.read_parquet(FILE)

# Dictionary source: https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf

payment_dict = {
    0: "Flex Fare trip",
    1: "Credit cards",
    2: "Cash",
    3: "No charge",
    4: "Dispute",
    5: "Unknown",
    6: "Voided trip"
}

vendor_dict = {
    1: "Creative Mobile Technologies",
    2: "Curb Mobility",
    6: "Myle Technologies",
    7: "Helix"
}

ratecodes_dict = {
    1: "standard", 
    2: "jfk", 
    3: "newark",
    4: "nassau_westchester", 
    5: "negotiated", 
    6: "group_ride",
    99: "null_unknown_sentinel"
}

print("1. are negative fare amounts corrections?")
negative = df[df["fare_amount"] < 0]
print("payment_type for NEGATIVE fare_amount:")
print(negative["payment_type"].map(payment_dict).value_counts().sort_index())
print("\npayment_type for ALL rows:")
print(df["payment_type"].map(payment_dict).value_counts().sort_index())

print("\n2. are missing values in 5 columns the same rows?")
block = ["passenger_count", "RatecodeID", "store_and_fwd_flag",
         "congestion_surcharge", "Airport_fee"]
missing_all_block = df[block].isna().all(axis=1)
missing_all_block_count = missing_all_block.sum()
print("conclusion:")
if missing_all_block_count == 140162:
    print("140,162 confirmed: it's one segment of records)")
else:
    print(f"No, they are all not the same rows.")
    print(f"Amount of rows with missing values in all 5 columns: {missing_all_block_count:,}")

print("\n3. Who provides these records?")
print(df.loc[missing_all_block, "VendorID"].map(vendor_dict).value_counts())
print("\nVendorID in the entire file:")
print(df["VendorID"].map(vendor_dict).value_counts())

print("\n4. what sits in trips with zero distance?")
zero_dist = df[df["trip_distance"] == 0]
print(f"Number of rows: {len(zero_dist):,}")
print("\nDistribution of fare_amount in these trips:")
print(zero_dist["fare_amount"].describe())
print("\npayment_type in these trips:")
print(zero_dist["payment_type"].map(payment_dict).value_counts().sort_index())

