import logging
import os
from typing import Any, Generator, List

import psycopg
from dotenv import load_dotenv

from app.models import PriceModel, ProductModel, StoreModel

logger = logging.getLogger(__name__)

load_dotenv()


class SupabaseRepository:
    def __init__(self):
        self.user = os.getenv("user")
        self.password = os.getenv("password")
        self.host = os.getenv("host")
        self.port = os.getenv("port")
        self.dbname = os.getenv("dbname")

        if not all([self.user, self.password, self.host, self.port, self.dbname]):
            raise ValueError(
                "Fatal: Missing one or more database environment variables in .env"
            )

    def _connect(self):
        """Creates a new database connection."""
        return psycopg.connect(
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            dbname=self.dbname,
        )

    def _chunk_data(
        self, data: List[Any], chunk_size: int = 1000
    ) -> Generator[List[Any], None, None]:
        """Yields chunks of the data array to prevent locking the database."""
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    def has_prices_for_store(self, chain_code: str, store_code: str) -> bool:
        """Check if prices already exist for a specific chain and store."""
        query = """
            SELECT EXISTS (
                SELECT 1 FROM prices
                WHERE chain_code = %s AND store_code = %s
            );
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (chain_code, store_code))
                    return cur.fetchone()[0]
        except Exception as e:
            logger.error("Error checking existing prices: %s", e)
            return False

    def upsert_chain(self, chain_code: str, name: str):
        """Upsert a chain into the chains table."""
        upsert_query = """
            INSERT INTO chains (chain_code, name)
            VALUES (%s, %s)
            ON CONFLICT (chain_code) DO UPDATE SET
                name = EXCLUDED.name;
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(upsert_query, (chain_code, name))
                conn.commit()
                logger.info("Upserted chain %s (%s)", chain_code, name)
        except Exception as e:
            logger.error("Chain upsert failed: %s", e)
            raise

    def upsert_store(self, store: StoreModel):
        """Upsert a store into the stores table."""
        upsert_query = """
            INSERT INTO stores (chain_code, store_code, store_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (chain_code, store_code) DO UPDATE SET
                store_name = EXCLUDED.store_name;
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        upsert_query,
                        (
                            store.chain_code,
                            store.store_code,
                            store.store_name,
                        ),
                    )
                conn.commit()
                logger.info(
                    "Upserted store %s (%s)",
                    store.store_code,
                    store.store_name,
                )
        except Exception as e:
            logger.error("Store upsert failed: %s", e)
            raise

    def upsert_products(self, products: List[ProductModel]):
        """Bulk upsert products into the products table."""
        if not products:
            logger.info("No products to insert. Skipping.")
            return

        upsert_query = """
            INSERT INTO products (
                barcode,
                product_name,
                image_url,
                unit_name,
                total_quantity,
                manufacturer_name
            )
            VALUES (%s, %s, %s, %s, %s, %s)

            ON CONFLICT (barcode) DO UPDATE SET
                product_name = EXCLUDED.product_name,
                unit_name = EXCLUDED.unit_name,
                total_quantity = EXCLUDED.total_quantity,
                manufacturer_name = EXCLUDED.manufacturer_name;
        """

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    for chunk in self._chunk_data(products):
                        data_tuples = [
                            (
                                p.barcode,
                                p.product_name,
                                p.image_url,
                                p.unit_name,
                                p.total_quantity,
                                p.manufacturer_name,
                            )
                            for p in chunk
                        ]
                        cur.executemany(upsert_query, data_tuples)

                conn.commit()
                logger.info("Successfully upserted %d products.", len(products))

        except Exception as e:
            logger.error("Product insertion failed: %s", e)
            raise

    def upsert_prices(self, prices: List[PriceModel]):
        """Executes a bulk UPSERT using the composite natural key (chain_code, store_code, barcode)."""
        if not prices:
            logger.info("No prices to insert. Skipping.")
            return

        upsert_query = """
            INSERT INTO prices (
                chain_code,
                store_code,
                barcode,
                price,
                price_per_unit,
                update_date
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_code, store_code, barcode) DO UPDATE SET
                price = EXCLUDED.price,
                price_per_unit = EXCLUDED.price_per_unit,
                update_date = EXCLUDED.update_date;
        """

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    for chunk in self._chunk_data(prices):
                        data_tuples = [
                            (
                                p.chain_code,
                                p.store_code,
                                p.barcode,
                                p.price,
                                p.price_per_unit,
                                p.update_date,
                            )
                            for p in chunk
                        ]

                        cur.executemany(upsert_query, data_tuples)

                # Commit the transaction only when ALL chunks succeed.
                conn.commit()
                logger.info(
                    "Successfully upserted %d prices for chain=%s, store=%s.",
                    len(prices),
                    prices[0].chain_code,
                    prices[0].store_code,
                )

        except Exception as e:
            logger.error("Database insertion failed: %s", e)
            raise
