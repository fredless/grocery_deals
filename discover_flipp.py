"""Print the Flipp flyers (merchant name + slug + flyer id) available near a postal code.

Usage: python discover_flipp.py 95018
Use the output to fill in "merchant" (and optionally "store_code") in stores.json.
"""
import sys
import requests

postal = sys.argv[1] if len(sys.argv) > 1 else "95018"
r = requests.get(
    "https://backflipp.wishabi.com/flipp/flyers",
    params={"postal_code": postal, "locale": "en-US"},
    timeout=30,
)
r.raise_for_status()
for f in r.json().get("flyers", []):
    print(f"{f.get('merchant'):35} slug={f.get('merchant_slug') or f.get('merchant', '').lower().replace(' ', '_'):25} "
          f"flyer_id={f.get('id')} valid {f.get('valid_from')} -> {f.get('valid_to')}")
