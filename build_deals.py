import pandas as pd
import json
import csv
import os

stores = json.load(open("stores.json"))
# stores are in California; the runner's clock is UTC, which is already "tomorrow" in the evening
today = pd.Timestamp.now(tz='America/Los_Angeles').tz_localize(None).normalize()

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
    d["special_weekday"] = (store.get("daily_special") or {}).get("weekday", "")
    frames.append(d)

if not frames:
    with open("deals.json", "w") as f:
        json.dump({"active": [], "expired": []}, f)
    print("No data yet.")
    raise SystemExit

df = pd.concat(frames, ignore_index=True)

# Flipp images come back as http:// (blocked as mixed content on https Pages)
df['image_url'] = df['image_url'].str.replace(r'^http://', 'https://', regex=True)

# some brand strings arrive double-encoded (e.g. "HÃ¤agen-Dazs"); repair them when possible
def fix_text(s):
    try:
        return s.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
df['brand'] = df['brand'].map(fix_text)
df['end_date'] = pd.to_datetime(df['end_date'])
df['start_date'] = pd.to_datetime(df['start_date'])

# a store's recurring one-day special (e.g. Safeway $5 Fridays, Nob Hill $5 Mondays): a single-day deal on that store's weekday
df['daily_special'] = (
    df['start_date'].notna()
    & (df['start_date'] == df['end_date'])
    & (df['end_date'].dt.day_name() == df['special_weekday'])
)
df = df.drop(columns=['special_weekday'])
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
