import json
import re
import requests
import csv
import pandas as pd
from datetime import datetime, timedelta
import os
import time
import random
from google import genai
from dotenv import load_dotenv
from tenacity import retry, wait_exponential_jitter, stop_after_attempt, retry_if_exception_type

load_dotenv()

FLYERS_URL = "https://backflipp.wishabi.com/flipp/flyers"
FLYER_URL = "https://backflipp.wishabi.com/flipp/flyers/{}"
ITEM_URL = "https://backflipp.wishabi.com/flipp/items/{}"

STORES = json.load(open("stores.json"))
os.makedirs("data", exist_ok=True)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_flyers(store):
    """Current, upcoming and just-ended flyers for the store's merchant near its postal code."""
    r = requests.get(FLYERS_URL, params={"postal_code": store["postal_code"], "locale": "en-US"}, timeout=30)
    r.raise_for_status()
    want = norm(store["merchant"])
    # keep flyers that ended in the last week too, so a flyer that lapsed before its successor is published isn't missed
    cutoff = (datetime.now().date() - timedelta(days=7)).isoformat()
    flyers = [
        f for f in r.json().get("flyers", [])
        if want in (norm(f.get("merchant")), norm(f.get("merchant_slug")))
        and (f.get("valid_to") or "")[:10] >= cutoff
    ]
    return sorted(flyers, key=lambda f: f.get("valid_from") or "")


def item_details(item_id):
    """Per-item detail (sale text, unit text, regular price, SKU). The flyer's item list omits these.
    Returns {} on any failure so the scrape still works with just the list data."""
    try:
        r = requests.get(ITEM_URL.format(item_id), params={"locale": "en-US"}, timeout=30)
        if r.status_code != 200:
            return {}
        data = r.json()
        return data.get("item", data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def date_only(v):
    return (v or "")[:10]


def ingest(store):
    sid = store["id"]
    filename = f"data/{sid}_prices.csv"
    seen_pubs_file = f"data/{sid}_seen_publications.txt"

    flyers = find_flyers(store)
    if not flyers:
        print(f"[{sid}] No current flyers found")
        return filename

    seen_pubs = set(open(seen_pubs_file).read().splitlines()) if os.path.exists(seen_pubs_file) else set()

    for flyer in flyers:
        fid = str(flyer["id"])
        if fid in seen_pubs:
            print(f"[{sid}] Flyer {fid} already processed, skipping.")
            continue

        r = requests.get(FLYER_URL.format(fid), params={"locale": "en-US"}, timeout=60)
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            print(f"[{sid}] Flyer {fid} has no items yet, will retry next run")
            continue

        if os.path.exists(filename):
            existing_df = pd.read_csv(filename, dtype=str)
        else:
            existing_df = pd.DataFrame(columns=["name", "start_date", "end_date"])
        existing_keys = set(zip(existing_df["name"], existing_df["start_date"], existing_df["end_date"]))

        print(f"[{sid}] Flyer {fid}: {len(items)} items")

        rows = []
        detailed = 0
        for item in items:
            name = item.get("name")
            if not name:
                continue
            start = date_only(item.get("valid_from") or flyer.get("valid_from"))
            end = date_only(item.get("valid_to") or flyer.get("valid_to"))
            if (name, start, end) in existing_keys:
                continue
            existing_keys.add((name, start, end))

            d = item_details(item.get("id"))
            if d:
                detailed += 1
                if detailed == 1:
                    print(f"[{sid}] item detail fields: {sorted(d.keys())}")
                time.sleep(random.uniform(0.05, 0.15))

            rows.append({
                "timestamp": datetime.now().isoformat(),
                "id": item.get("id"),
                "name": name,
                "sale_desc": d.get("sale_story"),
                "SKU": d.get("sku"),
                "pre_price_text": d.get("pre_price_text"),
                "sale_price": d.get("current_price") or item.get("price"),
                "post_price_text": d.get("post_price_text"),
                "regular_price": d.get("original_price"),
                "brand": item.get("brand") or d.get("brand"),
                "start_date": start,
                "end_date": end,
                "category": None,
                "image_url": item.get("cutout_image_url") or d.get("image_url"),
            })
        print(f"[{sid}] Detail fetched for {detailed}/{len(rows)} new items")

        if rows:
            df_new = pd.DataFrame(rows)
            if not os.path.exists(filename):
                df_new.to_csv(filename, index=False, quoting=csv.QUOTE_ALL)
            else:
                with open(filename, "rb+") as f:
                    f.seek(-1, 2)
                    if f.read(1) != b"\n":
                        f.write(b"\n")
                df_new.to_csv(filename, mode="a", header=False, index=False, quoting=csv.QUOTE_ALL)
        print(f"[{sid}] Added {len(rows)} new items")

        with open(seen_pubs_file, "a") as f:
            f.write(fid + "\n")

    return filename


# CATEGORIZATION

client = genai.Client(api_key=os.getenv("GEMINI_KEY"))

CATEGORIES = [
    "Produce",
    "Meat & Seafood",
    "Dairy & Eggs",
    "Bakery",
    "Deli & Prepared Foods",
    "Frozen",
    "Pantry",
    "Snacks",
    "Beverages",
    "Health & Wellness",
    "Personal Care",
    "Household",
    "Floral",
    "Other"
]

# RETRY-SAFE GEMINI CALL

class GeminiTransientError(Exception):
    pass

@retry(
    wait=wait_exponential_jitter(initial=2, max=30),
    stop=stop_after_attempt(5)
)
def call_gemini(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt
        )
        return response
    except Exception as e:
        # treat all transient API failures as retryable
        raise GeminiTransientError(str(e))

# BATCH CATEGORIZATION

def categorize_batch(df, uncategorized, filename, batch_size=10):

    for i in range(0, len(uncategorized), batch_size):
        batch = uncategorized.iloc[i:i+batch_size]

        print(f"Categorizing {min(i+batch_size, len(uncategorized))} / {len(uncategorized)}")

        prompt = f"""Categorize each grocery item into one of: {CATEGORIES}

Items:
{chr(10).join(f"{j+1}. {name}" for j, name in enumerate(batch["name"]))}

Respond with only a numbered list of category names.
"""

        response = call_gemini(prompt)

        lines = [
            l.split(". ", 1)[-1].strip()
            for l in response.text.strip().split("\n")
            if l.strip() and l.strip()[0].isdigit()
        ]

        # validate categories
        valid_set = set(CATEGORIES)
        lines = [l if l in valid_set else "Other" for l in lines]

        # pad if mismatch
        if len(lines) != len(batch):
            print(f"⚠️ mismatch: expected {len(batch)}, got {len(lines)}")
            lines += ["Other"] * (len(batch) - len(lines))

        df.loc[batch.index, "category"] = lines

        # write incremental safety checkpoint
        df.to_csv(filename, index=False, quoting=csv.QUOTE_ALL)

        time.sleep(2.5 + random.uniform(0, 1.5))

# RUN

for store in STORES:
    print(f"=== {store['id']} ===")
    filename = ingest(store)
    if not filename or not os.path.exists(filename):
        continue

    df = pd.read_csv(filename, dtype=str)
    if "category" not in df.columns:
        df["category"] = None

    uncategorized = df[df["category"].isna()]

    if uncategorized.empty:
        print("All items already categorized, skipping API call.")
    else:
        print(f"Categorizing {len(uncategorized)} items...")
        categorize_batch(df, uncategorized, filename)
        print("Done.")
