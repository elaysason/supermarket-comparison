import argparse
import logging
import os

from app.db.repository import SupabaseRepository
from app.scrapers.base import FileType, PriceUpdateStrategy
from app.scrapers.registry import get_scrapers

logger = logging.getLogger(__name__)


def main(force_full: bool = False):
    scrapers = get_scrapers()

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
        scraper.reset_file_cache()

        if not scraper.online_store:
            logger.error("No online store set. Skipping %s.", scraper.chain_name)
            continue

        # 2. Determine file type / fallback behavior
        price_files_to_try = []
        if force_full:
            price_files_to_try = [FileType.PRICE_FULL]
            logger.info(
                "force_full enabled. Downloading full price file for %s.",
                scraper.chain_name,
            )
        elif scraper.price_update_strategy == PriceUpdateStrategy.FULL_ONLY:
            price_files_to_try = [FileType.PRICE_FULL]
            logger.info("Using full price file strategy for %s.", scraper.chain_name)
        elif (
            scraper.price_update_strategy
            == PriceUpdateStrategy.DELTA_WITH_FULL_FALLBACK
        ):
            if repo.has_prices_for_store(scraper.chain_code, scraper.online_store):
                price_files_to_try = [FileType.PRICE_DELTA, FileType.PRICE_FULL]
                logger.info(
                    "Existing prices found. Trying delta price file with full fallback."
                )
            else:
                price_files_to_try = [FileType.PRICE_FULL]
                logger.info("No existing prices found. Downloading full price file.")
        else:
            price_files_to_try = [FileType.PRICE_FULL]
            logger.info(
                "Unknown price update strategy for %s. Falling back to "
                "full price file.",
                scraper.chain_name,
            )

        # 3. Download the latest usable price file
        file_path = None
        selected_file_type = None
        for candidate_file_type in price_files_to_try:
            file_path = scraper.download_latest(candidate_file_type)
            if file_path:
                selected_file_type = candidate_file_type
                logger.info("Using %s file: %s", candidate_file_type.value, file_path)
                break

            logger.warning(
                "No usable %s file for %s.",
                candidate_file_type.value,
                scraper.chain_name,
            )
            scraper.reset_file_cache()

        if file_path and selected_file_type is not None:
            # 4. Parse the XML and insert prices into DB
            logger.info("Parsing %s file: %s", selected_file_type.value, file_path)

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
            skipped = getattr(scraper, "last_parse_skipped", 0)
            summary.append((scraper.chain_name, len(products), skipped))
        else:
            logger.warning("No usable price file found for %s.", scraper.chain_name)

    print("\n=== Scraping Summary ===")
    for name, count, skipped in summary:
        print(f"  {name:<12}  {count} items upserted, {skipped} skipped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run supermarket price scrapers.")
    parser.add_argument(
        "--force-full",
        action="store_true",
        default=os.getenv("FORCE_FULL", "").lower() in ("1", "true", "yes"),
        help=(
            "Force a full price file download for every chain, ignoring the "
            "scraper's price_update_strategy. Can also be enabled via "
            "FORCE_FULL=1 env var."
        ),
    )
    args = parser.parse_args()
    main(force_full=args.force_full)
