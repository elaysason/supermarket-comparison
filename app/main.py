from app.db.repository import SupabaseRepository
from app.scrapers.base import FileType
from app.scrapers.chains.shufersal import ShufersalScraper


def main():
    # 1. Download the latest price file
    scraper = ShufersalScraper()
    latest_file_url = scraper.get_latest_file_url(FileType.PRICE_FULL)

    if latest_file_url:
        print(f"Latest file URL: {latest_file_url}")
        file_path = scraper.download_latest()

        if file_path:
            # 2. Parse the XML and insert prices into DB
            print(f"Parsing file: {file_path}")
            repo = SupabaseRepository()

            # parse() is a generator, collect products and prices
            products = []
            prices = []

            for item in scraper.parse(file_path):
                if item:
                    if "product" in item:
                        products.append(item["product"])
                    if "price" in item:
                        prices.append(item["price"])

            # 3. Upsert products first (prices FK depends on products)
            repo.upsert_products(products)
            repo.upsert_prices(prices)
    else:
        print("No latest file URL found.")


if __name__ == "__main__":
    main()
