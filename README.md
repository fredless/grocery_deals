# Weekly Ad Viewer — Felton / Scotts Valley

Weekly-ad viewer for:

- **Safeway** — 6255 Graham Hill Rd, Felton, CA 95018
- **Nob Hill Foods** — 222 Mt Hermon Rd, Scotts Valley, CA 95066

Forked from the North Berkeley Safeway viewer. Stores are defined in `stores.json`.

## Setup

1. Repo secrets: `FLIPP_TOKEN` (Flipp API access token) and `GEMINI_KEY` (item categorization).
   `FLIPP_POSTAL` / `FLIPP_STORE` are no longer used; postal code and store code live in `stores.json`.
2. Run `python discover_flipp.py 95018` (and `95066`) to list flyers near each postal code, and confirm the
   `merchant` slug in `stores.json`. The Nob Hill slug (`nob_hill_foods`) is a guess until verified this way.
   If a store's flyer is location-specific, also set `store_code`.
3. Run the **Scrape Weekly Ads** workflow manually once, then enable GitHub Pages.

## Files

- `scrape.py` — per store: fetch current Flipp flyer, append to `data/<id>_prices.csv`, categorize new items.
- `build_deals.py` — merges the CSVs into `deals.json` (each item tagged with `store`).
- `viewer.html` — static page with a store switcher.
