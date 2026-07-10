import argparse
import logging
import os
import sys

from app.db.repository import SupabaseRepository
from app.scrapers.base import FileType, PriceUpdateStrategy
from app.scrapers.common import parse_source_file_date
from app.scrapers.registry import get_scrapers

logger = logging.getLogger(__name__)


def main(force_full: bool = False):
    scrapers = get_scrapers()

    repo = SupabaseRepository()
    summary = []
    warnings = []
    failures = []
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
            reason = "no online store set"
            logger.error("No online store set. Skipping %s.", scraper.chain_name)
            failures.append((scraper.chain_name, reason))
            continue

        compare_store_code = repo.get_compare_store_code(scraper.chain_code)
        if not compare_store_code:
            reason = "no compare store configured"
            logger.error(
                "No compare store configured for %s (%s). Skipping.",
                scraper.chain_name,
                scraper.chain_code,
            )
            failures.append((scraper.chain_name, reason))
            continue

        if compare_store_code != scraper.online_store:
            reason = (
                f"online store {scraper.online_store} does not match "
                f"compare store {compare_store_code}"
            )
            logger.error(
                "Online store %s for %s does not match compare store %s. Skipping.",
                scraper.online_store,
                scraper.chain_name,
                compare_store_code,
            )
            failures.append((scraper.chain_name, reason))
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

        # 3. Download and parse the latest usable price file
        selected_file_type = None
        products = []
        prices = []
        for candidate_file_type in price_files_to_try:
            file_path = scraper.download_latest(candidate_file_type)
            if file_path:
                logger.info("Using %s file: %s", candidate_file_type.value, file_path)

                logger.info("Parsing %s file: %s", candidate_file_type.value, file_path)
                products = []
                prices = []

                for item in scraper.parse(file_path):
                    if item:
                        if "product" in item:
                            products.append(item["product"])
                        if "price" in item:
                            prices.append(item["price"])

                parse_failed = getattr(scraper, "last_parse_failed", False)
                if not parse_failed:
                    selected_file_type = candidate_file_type
                    break

                logger.warning(
                    "Failed to parse %s file for %s. Trying next candidate.",
                    candidate_file_type.value,
                    scraper.chain_name,
                )

            logger.warning(
                "No usable %s file for %s.",
                candidate_file_type.value,
                scraper.chain_name,
            )
            scraper.reset_file_cache()

        if selected_file_type is not None:
            skipped = getattr(scraper, "last_parse_skipped", 0)
            if skipped:
                failures.append(
                    (
                        scraper.chain_name,
                        f"{skipped} item rows skipped during parse",
                    )
                )
                continue

            if selected_file_type == FileType.PRICE_FULL and not prices:
                reason = "full price file parsed zero prices"
                logger.error(
                    "Full price file for %s parsed zero prices. Skipping freshness "
                    "update to avoid marking stale data as fresh.",
                    scraper.chain_name,
                )
                failures.append((scraper.chain_name, reason))
                continue

            # 4. Upsert products first (prices FK depends on products)
            repo.upsert_products(products)
            if selected_file_type == FileType.PRICE_FULL:
                repo.replace_store_prices(prices)
            else:
                repo.upsert_prices(prices)
            source_file_date = parse_source_file_date(file_path)
            if source_file_date and scraper.online_store:
                repo.upsert_price_import_status(
                    chain_code=scraper.chain_code,
                    store_code=scraper.online_store,
                    price_file_type=selected_file_type.value,
                    source_file_name=os.path.basename(file_path),
                    source_file_date=source_file_date,
                    items_imported=len(prices),
                )
            else:
                reason = "could not record import freshness"
                logger.warning(
                    "Could not record import freshness for %s from %s.",
                    scraper.chain_name,
                    file_path,
                )
                warnings.append((scraper.chain_name, reason))
            summary.append((scraper.chain_name, len(products), skipped))
        else:
            reason = "no usable price file found"
            logger.warning("No usable price file found for %s.", scraper.chain_name)
            failures.append((scraper.chain_name, reason))

    print("\n=== Scraping Summary ===")
    for name, count, skipped in summary:
        print(f"  {name:<12}  {count} items upserted, {skipped} skipped")

    if warnings:
        print("\n=== Scrape Warnings ===")
        for name, reason in warnings:
            print(f"  {name}: {reason}")

    if failures:
        print("\n=== Scrape Failures ===")
        for name, reason in failures:
            print(f"  {name} skipped: {reason}")
        return 1

    return 0


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
    sys.exit(main(force_full=args.force_full))
