import logging

from app.db.repository import SupabaseRepository
from app.scrapers.base import FileType
from app.scrapers.chains.hazi_hinam import HaziHinamScraper
from app.scrapers.chains.rami_levi import RamiLeviScraper
from app.scrapers.chains.shufersal import ShufersalScraper
from app.scrapers.chains.yohananof import YohananofScraper

logger = logging.getLogger(__name__)


def main():
    scrapers = [
        HaziHinamScraper(),
        YohananofScraper(),
        RamiLeviScraper(),
        ShufersalScraper(),
    ]

    repo = SupabaseRepository()
    summary = []
    for scraper in scrapers:
        logger.info("Processing scraper for %s", scraper.chain_name)

        # 0. Ensure the chain exists in the DB
        repo.upsert_chain(scraper.chain_code, scraper.chain_name)

        # 1. Download stores file to find the online store
        logger.info(
            "Fetching latest stores file for %s (chain code: %s).",
            scraper.chain_name,
            scraper.chain_code,
        )
        stores_path = scraper.download_latest(FileType.STORES)
        if stores_path:
            online_store = scraper.find_online_store(stores_path)
            if online_store:
                repo.upsert_store(online_store)
            else:
                logger.warning("No online store found in stores file.")
        else:
            logger.info("No stores file available. Using existing online store.")
        scraper._cached_file_url = None

        if not scraper.online_store:
            logger.error("No online store set. Skipping %s.", scraper.chain_name)
            continue

        # 2. Determine file type: use delta if full prices already loaded
        if repo.has_prices_for_store(scraper.chain_code, scraper.online_store):
            file_type = FileType.PRICE_DELTA
            logger.info(
                "Full prices already exist. Using delta price file for updates."
            )
        else:
            file_type = FileType.PRICE_FULL
            logger.info("No existing prices found. Downloading full price file.")

        # 3. Download the latest price file
        latest_file_url = scraper.get_latest_file_url(file_type)

        if latest_file_url:
            logger.info("Latest file URL: %s", latest_file_url)
            file_path = scraper.download_latest(file_type)

            if file_path:
                # 4. Parse the XML and insert prices into DB
                logger.info("Parsing file: %s", file_path)

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
                summary.append((scraper.chain_name, len(products)))
        else:
            logger.warning("No latest file URL found for %s.", scraper.chain_name)

    print("\n=== Scraping Summary ===")
    for name, count in summary:
        print(f"  {name:<12}  {count} items upserted")


if __name__ == "__main__":
    main()
