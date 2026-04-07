"""
Debug script: run the comparison logic directly and print all intermediate values.
"""
from dotenv import load_dotenv
load_dotenv()

from app.db.repository import SupabaseRepository

SOURCE = "7290058140886"  # Rami Levi
BARCODES = ["7290102399635", "7290112493934", "7290100850923", "7290005425196"]
QUANTITIES = {b: 1 for b in BARCODES}

repo = SupabaseRepository()

print("=== source prices ===")
source_data = repo.get_source_prices(SOURCE, BARCODES)
src = source_data.get(SOURCE)
if src:
    print(f"chain_name: {src['chain_name']}")
    for b, item in src["items"].items():
        print(f"  {b}: {item['price']}")
else:
    print("NO SOURCE DATA")

print()
print("=== competitor prices ===")
competitor_data = repo.get_competitor_prices(SOURCE, BARCODES)
for chain_code, chain in competitor_data.items():
    print(f"{chain['chain_name']} ({chain_code}):")
    for b, item in chain["items"].items():
        print(f"  {b}: {item['price']}")

print()
source_barcodes = set(src["items"].keys()) if src else set()
print(f"source_barcodes: {source_barcodes}")
print()

for chain_code, chain in competitor_data.items():
    total = round(sum(item["price"] for b, item in chain["items"].items() if b in source_barcodes), 2)
    matched = sum(1 for b in source_barcodes if b in chain["items"])
    print(f"{chain['chain_name']}: total={total}, matched={matched}/{len(source_barcodes)}")

src_total = round(sum(item["price"] for b, item in src["items"].items()), 2) if src else 0
print(f"Source ({src['chain_name']}): total={src_total}, matched={len(source_barcodes)}/{len(BARCODES)}")
