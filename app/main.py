from app.db.repository import SupabaseRepository
from app.scrapers.base import FileType
from app.scrapers.chains.shufersal import ShufersalScraper


def main():
    scraper = ShufersalScraper()
    repo = SupabaseRepository()

    # 1. Download stores file to find the online store
    stores_url = scraper.get_latest_file_url(FileType.STORES)
    if not stores_url:
        print("Could not find stores file URL.")
        return

    stores_path = scraper.download_latest(FileType.STORES)
    if not stores_path:
        print("Failed to download stores file.")
        return

    online_store = scraper.find_online_store(stores_path)
    if not online_store:
        print("No online store found in stores file.")
        return

    # Upsert the online store into the DB
    repo.upsert_store(online_store)

    # Reset cached URL so price file can be fetched next
    scraper._cached_file_url = None

    # 2. Determine file type: use delta if full prices already loaded
    if repo.has_prices_for_store(
        scraper.chain_code, scraper.online_store
    ):
        file_type = FileType.PRICE_DELETA
        print(
            "Full prices already exist. "
            "Using delta price file for updates."
        )
    else:
        file_type = FileType.PRICE_FULL
        print(
            "No existing prices found. "
            "Downloading full price file."
        )

    # 3. Download the latest price file
    latest_file_url = scraper.get_latest_file_url(file_type)

    if latest_file_url:
        print(f"Latest file URL: {latest_file_url}")
        file_path = scraper.download_latest(file_type)

        if file_path:
            # 4. Parse the XML and insert prices into DB
            print(f"Parsing file: {file_path}")

            products = []
            prices = []

            for item in scraper.parse(file_path):
                if item:
                    if "product" in item:
                        products.append(item["product"])
                    if "price" in item:
                        prices.append(item["price"])

            # 5. Upsert products first (prices FK depends on products)
            repo.upsert_products(products)
            repo.upsert_prices(prices)
    else:
        print("No latest file URL found.")


if __name__ == "__main__":
    main()
