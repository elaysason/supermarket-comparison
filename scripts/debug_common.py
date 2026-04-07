from dotenv import load_dotenv; load_dotenv()
from app.db.repository import SupabaseRepository
repo = SupabaseRepository()
SOURCE = "7290058140886"
BARCODES = ["7290102399635","7290112493934","7290100850923","7290005425196"]
src = repo.get_source_prices(SOURCE, BARCODES).get(SOURCE)
comp = repo.get_competitor_prices(SOURCE, BARCODES)
all_comp_barcodes = set()
for c in comp.values():
    all_comp_barcodes |= set(c["items"].keys())
common = set(src["items"].keys()) & all_comp_barcodes
print("common set:", common)
print("excluded (source-only):", set(src["items"].keys()) - common)
src_total = sum(src["items"][b]["price"] for b in common)
print(f"Source total over common: {src_total:.2f}")
for cc, chain in comp.items():
    t = sum(chain["items"][b]["price"] for b in common if b in chain["items"])
    name = chain["chain_name"]
    print(f"{name}: {t:.2f}")
