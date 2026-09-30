import pandas as pd
import json
import csv
import os

stores = json.load(open("stores.json"))
today = pd.Timestamp('today').normalize()

frames = []
for store in stores:
    path = f"data/{store['id']}_prices.csv"
    if not os.path.exists(path):
        continue
    with open(path, "r") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        continue
    d = pd.DataFrame(rows[1:], columns=rows[0])
    d["store"] = store["id"]
    frames.append(d)

if not frames:
    with open("deals.json", "w") as f:
        json.dump({"active": [], "expired": []}, f)
    print("No data yet.")
    raise SystemExit

df = pd.concat(frames, ignore_index=True)
df['end_date'] = pd.to_datetime(df['end_date'])
df['start_date'] = pd.to_datetime(df['start_date'])

# single-day deals (e.g. $5 Fridays)
df['friday_only'] = df['start_date'].notna() & (df['start_date'] == df['end_date'])
active_df   = df[df['end_date'] >= today].sort_values('name')
expired_df  = df[df['end_date'] <  today].sort_values('name')

def to_records(d):
    d = d.copy()
    d['end_date'] = d['end_date'].astype(str)
    d['start_date'] = d['start_date'].astype(str)
    return d.fillna("").to_dict(orient="records")

with open("deals.json", "w") as f:
    json.dump({"active": to_records(active_df), "expired": to_records(expired_df)}, f)

print(f"Done. {len(active_df)} active, {len(expired_df)} expired.")
