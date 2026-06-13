import logging
import os
from typing import Any, Dict, Generator, List

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from app.models import PriceModel, ProductModel, StoreModel

logger = logging.getLogger(__name__)

load_dotenv()


def _env_any(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _positive_int_env(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", name, value)
        return None
    if parsed <= 0:
        logger.warning("Ignoring invalid %s=%r", name, value)
        return None
    return parsed


def _build_conninfo() -> str:
    database_url = _env_any("DATABASE_URL")
    if database_url:
        return database_url

    user = _env_any("PGUSER", "POSTGRES_USER", "user")
    password = _env_any("PGPASSWORD", "POSTGRES_PASSWORD", "password")
    host = _env_any("PGHOST", "POSTGRES_HOST", "host")
    port = _env_any("PGPORT", "POSTGRES_PORT", "port")
    dbname = _env_any("PGDATABASE", "POSTGRES_DB", "dbname")
    sslmode = _env_any("PGSSLMODE", "DB_SSLMODE") or "require"

    if not all([user, password, host, port, dbname]):
        raise ValueError(
            "Fatal: set DATABASE_URL or all database env vars: "
            "PGUSER/PGPASSWORD/PGHOST/PGPORT/PGDATABASE"
        )
    return (
        f"user={user} password={password} host={host} port={port} "
        f"dbname={dbname} sslmode={sslmode}"
    )


def _connection_kwargs() -> dict[str, str]:
    timeout_ms = _positive_int_env("DATABASE_STATEMENT_TIMEOUT_MS")
    if timeout_ms is None:
        return {}
    return {"options": f"-c statement_timeout={timeout_ms}"}


_pool_min_size = _positive_int_env("DATABASE_POOL_MIN_SIZE", 1) or 1
_pool_max_size = _positive_int_env("DATABASE_POOL_MAX_SIZE", 3) or 3
if _pool_min_size > _pool_max_size:
    raise ValueError("DATABASE_POOL_MIN_SIZE must be <= DATABASE_POOL_MAX_SIZE")

_pool = ConnectionPool(
    _build_conninfo(),
    min_size=_pool_min_size,
    max_size=_pool_max_size,
    kwargs=_connection_kwargs(),
)


class SupabaseRepository:
    def ping(self) -> None:
        """Run a minimal query to verify database connectivity."""
        with _pool.connection(timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

    def _chunk_data(
        self, data: List[Any], chunk_size: int = 1000
    ) -> Generator[List[Any], None, None]:
        """Yields chunks of the data array to prevent locking the database."""
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    def get_compare_store_code(self, chain_code: str) -> str | None:
        """Return the store currently used for chain-level comparison."""
        query = """
            SELECT store_code
            FROM chain_compare_stores
            WHERE chain_code = %s
        """
        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (chain_code,))
                    row = cur.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error("Error fetching compare store for chain %s: %s", chain_code, e)
            raise

    def has_prices_for_store(self, chain_code: str, store_code: str) -> bool:
        """Check if prices already exist for a specific chain and store."""
        query = """
            SELECT EXISTS (
                SELECT 1 FROM prices
                WHERE chain_code = %s AND store_code = %s
            );
        """
        try:
            with _pool.connection() as conn:
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
            with _pool.connection() as conn:
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
            with _pool.connection() as conn:
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
            with _pool.connection() as conn:
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
        """Bulk upsert prices using the composite natural key."""
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
            with _pool.connection() as conn:
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

    def get_shipping_costs(self, chain_codes: List[str]) -> Dict[str, Any]:
        """
        Returns shipping options for the given chain codes.

        Result shape:
            {
                chain_code: [
                    {
                        "option_type": "delivery" | "pickup",
                        "fee": float,
                        "free_above": float | None,
                        "min_order": float | None,
                        "notes": str | None,
                    },
                    ...
                ],
                ...
            }
        """
        if not chain_codes:
            return {}
        query = """
            SELECT chain_code, option_type, fee, free_above, min_order, notes
            FROM shipping_costs
            WHERE chain_code = ANY(%s)
            ORDER BY chain_code, option_type
        """
        result: Dict[str, Any] = {}
        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (chain_codes,))
                    for (
                        chain_code,
                        option_type,
                        fee,
                        free_above,
                        min_order,
                        notes,
                    ) in cur.fetchall():
                        result.setdefault(chain_code, []).append(
                            {
                                "option_type": option_type,
                                "fee": float(fee),
                                "free_above": (
                                    float(free_above)
                                    if free_above is not None
                                    else None
                                ),
                                "min_order": (
                                    float(min_order) if min_order is not None else None
                                ),
                                "notes": notes,
                            }
                        )
        except Exception as e:
            logger.error("Error fetching shipping costs: %s", e)
        return result

    def get_product_names(self, barcodes: List[str]) -> Dict[str, str]:
        """
        Returns a dict mapping barcode -> product_name for all barcodes that
        exist in the products table. Barcodes not in the table are absent from
        the result.
        """
        if not barcodes:
            return {}
        query = "SELECT barcode, product_name FROM products WHERE barcode = ANY(%s)"
        result: Dict[str, str] = {}
        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (barcodes,))
                    for barcode, product_name in cur.fetchall():
                        if product_name:
                            result[barcode] = product_name
        except Exception as e:
            logger.error("Error fetching product names: %s", e)
        return result

    def get_source_prices(
        self, source_chain_code: str, barcodes: List[str]
    ) -> Dict[str, Any]:
        """
        Returns price data for the source chain itself (the chain the user is
        currently shopping at), for the given barcodes.

        Result shape mirrors get_competitor_prices() but contains only one entry:
            {
                source_chain_code: {
                    "chain_name": str,
                    "items": {barcode: {"product_name": str|None, "price": float}},
                    "matched_count": int,
                }
            }
        Prices are scoped to the DB-selected compare store for the source chain.
        Returns {} if no compare store or prices are found.
        """
        if not barcodes:
            return {}

        query = """
            SELECT
                p.chain_code,
                c.name            AS chain_name,
                p.barcode,
                pr.product_name,
                p.price
            FROM prices p
            JOIN chains c ON c.chain_code = p.chain_code
            JOIN chain_compare_stores ccs
              ON ccs.chain_code = p.chain_code
             AND ccs.store_code = p.store_code
            LEFT JOIN products pr ON pr.barcode = p.barcode
            WHERE p.chain_code = %s
              AND p.barcode = ANY(%s)
            ORDER BY p.barcode, p.price ASC
        """

        results: Dict[str, Any] = {}
        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (source_chain_code, barcodes))
                    rows = cur.fetchall()

            for chain_code, chain_name, barcode, product_name, price in rows:
                if chain_code not in results:
                    results[chain_code] = {"chain_name": chain_name, "items": {}}
                if barcode not in results[chain_code]["items"]:
                    results[chain_code]["items"][barcode] = {
                        "product_name": product_name,
                        "price": float(price),
                    }

            for chain_code in results:
                results[chain_code]["matched_count"] = len(results[chain_code]["items"])

        except Exception as e:
            logger.error("Error fetching source prices: %s", e)
            raise

        return results

    def get_competitor_prices(
        self, source_chain_code: str, barcodes: List[str]
    ) -> Dict[str, Any]:
        """
        For a list of barcodes, find the total price at every chain EXCEPT
        the source chain. Each chain is scoped to one DB-selected compare
        store so we do not mix multiple sub-chains under the same chain entry.
        Returns a dict keyed by chain_code.

        Each entry contains:
          - chain_name: str
          - total_price: float  (sum of cheapest-per-barcode prices)
          - matched_count: int
          - items: dict[barcode -> {"product_name": str|None, "price": float}]

        Only the first price seen per (chain, barcode) pair is used.
        """
        if not barcodes:
            return {}

        query = """
            SELECT
                p.chain_code,
                c.name            AS chain_name,
                p.barcode,
                pr.product_name,
                p.price
            FROM prices p
            JOIN chains c ON c.chain_code = p.chain_code
            JOIN chain_compare_stores ccs
              ON ccs.chain_code = p.chain_code
             AND ccs.store_code = p.store_code
            LEFT JOIN products pr ON pr.barcode = p.barcode
            WHERE p.chain_code != %s
              AND p.barcode = ANY(%s)
            ORDER BY p.chain_code, p.barcode, p.price ASC
        """

        # results[chain_code] = {
        #   "chain_name": str,
        #   "total_price": float,
        #   "items": {barcode: {"product_name": str|None, "price": float}},
        # }
        results: Dict[str, Any] = {}

        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (source_chain_code, barcodes))
                    rows = cur.fetchall()

            for chain_code, chain_name, barcode, product_name, price in rows:
                if chain_code not in results:
                    results[chain_code] = {
                        "chain_name": chain_name,
                        "total_price": 0.0,
                        "items": {},
                    }
                # First price seen per (chain, barcode) wins.
                if barcode not in results[chain_code]["items"]:
                    results[chain_code]["items"][barcode] = {
                        "product_name": product_name,
                        "price": float(price),
                    }
                    results[chain_code]["total_price"] += float(price)

            # Round totals and compute matched_count
            for chain_code in results:
                results[chain_code]["total_price"] = round(
                    results[chain_code]["total_price"], 2
                )
                results[chain_code]["matched_count"] = len(results[chain_code]["items"])

        except Exception as e:
            logger.error("Error fetching competitor prices: %s", e)
            raise

        return results
