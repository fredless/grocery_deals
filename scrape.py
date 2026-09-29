import json
import requests
import csv
import pandas as pd
from datetime import datetime
import os
import time
import random
from google import genai
from dotenv import load_dotenv
from tenacity import retry, wait_exponential_jitter, stop_after_attempt, retry_if_exception_type

load_dotenv()

BASE = "https://api.flipp.com/flyerkit/v4.0/publications"

STORES = json.load(open("stores.json"))
TOKEN = os.getenv("FLIPP_TOKEN")
os.makedirs("data", exist_ok=True)

def ingest(store):
    sid = store["id"]
    filename = f"data/{sid}_prices.csv"
    seen_pubs_file = f"data/{sid}_seen_publications.txt"

    params_publication = {
        "access_token": TOKEN,
        "locale": "en-US",
        "postal_code": store["postal_code"],
    }
    if store.get("store_code"):
        params_publication["store_code"] = store["store_code"]

    r = requests.get(f"{BASE}/{store['merchant']}", params=params_publication)
    publications = r.json()
    if not publications:
        print(f"[{sid}] No publications found")
        return None

    current_pub = publications[0]["id"]

    if os.path.exists(seen_pubs_file):
        with open(seen_pubs_file) as f:
            seen_pubs = set(f.read().splitlines())
    else:
        seen_pubs = set()

    if str(current_pub) in seen_pubs:
        print(f"[{sid}] Publication {current_pub} already processed, skipping.")
        return filename

    PRODUCTS_URL = f"https://dam.flippenterprise.net/flyerkit/publication/{current_pub}/products"

    params_product = {
        "display_type": "all",
        "locale": "en-US",
        "access_token": TOKEN
    }

    r = requests.get(PRODUCTS_URL, params=params_product)
    items = r.json()

    if not items:
        print("Warning: No products found in the current publication")
        return filename

    if os.path.exists(filename):
        existing_df = pd.read_csv(filename)
    else:
        existing_df = pd.DataFrame(columns=["name", "start_date", "end_date"])

    print(f"Number of Items: {len(items)}")

    rows = []

    # INGEST PRODUCTS

    for index, item in enumerate(items, start=1):
        pid = item.get("id")

        if not pid:
            print("Skipped item (missing ID)")
            continue

        url = f"https://dam.flippenterprise.net/flyerkit/product/{pid}"
        r = requests.get(url, params=params_product)

        if r.status_code != 200:
            print("Failed:", pid)
            continue

        data = r.json()

        row = {
            "timestamp": datetime.now().isoformat(),
            "id": data.get("id"),
            "name": data.get("name"),
            "sale_desc": data.get("sale_story"),
            "SKU": data.get("sku"),
            "pre_price_text": data.get("pre_price_text"),
            "sale_price": data.get("price_text"),
            "post_price_text": data.get("post_price_text"),
            "regular_price": data.get("original_price"),
            "brand": data.get("brand"),
            "start_date": data.get("valid_from"),
            "end_date": data.get("valid_to"),
            "image_url": data.get("image_url")
        }

        is_duplicate = (
            (existing_df["name"] == row["name"]) &
            (existing_df["start_date"] == row["start_date"]) &
            (existing_df["end_date"] == row["end_date"])
        )

        if is_duplicate.any():
            print(f"Skipped duplicate: {row['name']}")
            continue

        rows.append(row)

        print(f"[{index}/{len(items)}] {data.get('name')}")

        time.sleep(random.uniform(0.1, 0.3))

    # WRITE CSV

    if rows:
        df_new = pd.DataFrame(rows)
        df_new["category"] = None

        df_new = df_new[
            [
                "timestamp","id","name","sale_desc","SKU",
                "pre_price_text","sale_price","post_price_text",
                "regular_price","brand","start_date","end_date",
                "category","image_url"
            ]
        ]

        if not os.path.exists(filename):
            df_new.to_csv(filename, index=False, quoting=csv.QUOTE_ALL)
        else:
            with open(filename, "rb+") as f:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    f.write(b"\n")
            df_new.to_csv(filename, mode="a", header=False, index=False, quoting=csv.QUOTE_ALL)

    # mark publication as processed
    with open(seen_pubs_file, "a") as f:
        f.write(str(current_pub) + "\n")


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

    df = pd.read_csv(filename)
    if "category" not in df.columns:
        df["category"] = None

    uncategorized = df[df["category"].isna()]

    if uncategorized.empty:
        print("All items already categorized, skipping API call.")
    else:
        print(f"Categorizing {len(uncategorized)} items...")
        categorize_batch(df, uncategorized, filename)
        print("Done.")
