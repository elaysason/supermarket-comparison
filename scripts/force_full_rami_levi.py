"""
Force a full price reload for Rami Levi by deleting its existing prices,
then running the scraper so it falls through to FileType.PRICE_FULL.
"""
import logging
import os

import psycopg
from dotenv import load_dotenv

from app.db.repository import SupabaseRepository
from app.scrapers.base import FileType
from app.scrapers.chains.rami_levi import RamiLeviScraper

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHAIN_CODE = "7290058140886"


def delete_rami_levi_prices(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM prices WHERE chain_code = %s", (CHAIN_CODE,))
        deleted = cur.rowcount
    conn.commit()
    logger.info("Deleted %d existing Rami Levi price rows.", deleted)


def main():
    conn = psycopg.connect(
        user=os.getenv("user"),
        password=os.getenv("password"),
        host=os.getenv("host"),
        port=os.getenv("port"),
        dbname=os.getenv("dbname"),
    )

    delete_rami_levi_prices(conn)
    conn.close()

    repo = SupabaseRepository()
    scraper = RamiLeviScraper()

    repo.upsert_chain(scraper.chain_code, scraper.chain_name)

    logger.info("Fetching stores file...")
    stores_path = scraper.download_latest(FileType.STORES)
    if stores_path:
        online_store = scraper.find_online_store(stores_path)
        if online_store:
            repo.upsert_store(online_store)
    scraper._cached_file_url = None

    if not scraper.online_store:
        logger.error("No online store found. Aborting.")
        return

    # has_prices_for_store now returns False, so PRICE_FULL will be used
    assert not repo.has_prices_for_store(scraper.chain_code, scraper.online_store), \
        "Prices were not deleted — aborting to avoid delta run."

    logger.info("Downloading full price file...")
    file_path = scraper.download_latest(FileType.PRICE_FULL)
    if not file_path:
        logger.error("No full price file found. Aborting.")
        return

    logger.info("Parsing %s ...", file_path)
    products, prices = [], []
    for item in scraper.parse(file_path):
        if item:
            if "product" in item:
                products.append(item["product"])
            if "price" in item:
                prices.append(item["price"])

    logger.info("Upserting %d products and %d prices...", len(products), len(prices))
    repo.upsert_products(products)
    repo.upsert_prices(prices)
    logger.info("Done.")


if __name__ == "__main__":
    main()
