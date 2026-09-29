# Safeway Weekly Ad Viewer

This website uses flipp's api to scrape each item on Safeway's Weekly Ad. 
It then takes each item, and appends it to `data/<id>_prices.csv`. Nothing should ever deleted from `data/<id>_prices.csv`, only added.
`build_deals` reads `data/<id>_prices.csv` and converts it to a json file in `deals.json`. 
`deals.json` is then read to generate the website visuals. 
Since Safeway's Weekly Ad's change every week, I have github actions set up to run `scrape_safeway.py` every week. 
