import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Generator, List

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from app.models import PriceModel, ProductModel, StoreModel

logger = logging.getLogger(__name__)

load_dotenv()


_NAME_TOKEN_RE = re.compile(r"[\w\u0590-\u05ff]+", re.UNICODE)


def _normalize_name(value: str) -> str:
    tokens = _NAME_TOKEN_RE.findall((value or "").lower())
    return " ".join(tokens)


def _name_tokens(value: str) -> set[str]:
    return {token for token in _normalize_name(value).split() if len(token) >= 2}


def _numeric_tokens(value: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", value or ""))


def _name_match_score(cart_name: str, db_name: str) -> float:
    cart_norm = _normalize_name(cart_name)
    db_norm = _normalize_name(db_name)
    if not cart_norm or not db_norm:
        return 0.0

    cart_numbers = _numeric_tokens(cart_norm)
    db_numbers = _numeric_tokens(db_norm)
    if cart_numbers and db_numbers and not (cart_numbers & db_numbers):
        return 0.0

    if db_norm == cart_norm:
        return 1.0

    cart_tokens = _name_tokens(cart_norm)
    db_tokens = _name_tokens(db_norm)
    if not cart_tokens or not db_tokens:
        return 0.0

    overlap = len(cart_tokens & db_tokens)
    token_score = overlap / max(len(db_tokens | cart_tokens), 1)
    if token_score >= 0.9:
        return token_score
    return 0.0


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

    def replace_store_prices(self, prices: List[PriceModel]) -> None:
        """Upsert a full store snapshot and remove rows absent from it."""
        if not prices:
            logger.info("No prices to replace. Skipping.")
            return

        chain_code = prices[0].chain_code
        store_code = prices[0].store_code
        barcodes = [price.barcode for price in prices]
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
        delete_query = """
            DELETE FROM prices
            WHERE chain_code = %s
              AND store_code = %s
              AND NOT (barcode = ANY(%s));
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

                    cur.execute(delete_query, (chain_code, store_code, barcodes))
                    removed_count = cur.rowcount

                conn.commit()
                logger.info(
                    "Replaced %d prices for chain=%s, store=%s; removed %d stale rows.",
                    len(prices),
                    chain_code,
                    store_code,
                    removed_count,
                )
        except Exception as e:
            logger.error("Store price replacement failed: %s", e)
            raise

    def upsert_price_import_status(
        self,
        chain_code: str,
        store_code: str,
        price_file_type: str,
        source_file_name: str,
        source_file_date: datetime,
        items_imported: int,
    ) -> None:
        """Record the latest successfully imported supplier price file."""
        upsert_query = """
            INSERT INTO price_import_status (
                chain_code,
                store_code,
                price_file_type,
                source_file_name,
                source_file_date,
                last_success_at,
                items_imported
            )
            VALUES (%s, %s, %s, %s, %s, now(), %s)
            ON CONFLICT (chain_code, store_code) DO UPDATE SET
                price_file_type = EXCLUDED.price_file_type,
                source_file_name = EXCLUDED.source_file_name,
                source_file_date = EXCLUDED.source_file_date,
                last_success_at = now(),
                items_imported = EXCLUDED.items_imported;
        """

        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        upsert_query,
                        (
                            chain_code,
                            store_code,
                            price_file_type,
                            source_file_name,
                            source_file_date,
                            items_imported,
                        ),
                    )
                conn.commit()
                logger.info(
                    "Recorded import freshness for chain=%s, store=%s, file=%s.",
                    chain_code,
                    store_code,
                    source_file_name,
                )
        except Exception as e:
            logger.error("Import status upsert failed: %s", e)
            raise

    def get_compare_chain_statuses(self) -> Dict[str, Any]:
        """Return compare-store metadata with the latest price import status."""
        query = """
            SELECT
                ccs.chain_code,
                c.name,
                ccs.store_code,
                pis.source_file_date,
                pis.last_success_at,
                pis.source_file_name
            FROM chain_compare_stores ccs
            JOIN chains c ON c.chain_code = ccs.chain_code
            LEFT JOIN price_import_status pis
              ON pis.chain_code = ccs.chain_code
             AND pis.store_code = ccs.store_code
            ORDER BY c.name
        """
        result: Dict[str, Any] = {}
        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    for (
                        chain_code,
                        chain_name,
                        store_code,
                        source_file_date,
                        last_success_at,
                        source_file_name,
                    ) in cur.fetchall():
                        result[chain_code] = {
                            "chain_name": chain_name,
                            "store_code": store_code,
                            "source_file_date": source_file_date,
                            "last_success_at": last_success_at,
                            "source_file_name": source_file_name,
                        }
        except Exception as e:
            logger.error("Error fetching compare chain statuses: %s", e)
            raise
        return result

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

    def resolve_barcodes_by_names(
        self,
        source_chain_code: str,
        item_names: Dict[str, str],
    ) -> Dict[str, str]:
        """Map internal cart ids to barcodes by strict source-store name match."""
        if not item_names:
            return {}

        query = """
            SELECT p.barcode, pr.product_name
            FROM prices p
            JOIN chain_compare_stores ccs
              ON ccs.chain_code = p.chain_code
             AND ccs.store_code = p.store_code
            JOIN products pr ON pr.barcode = p.barcode
            WHERE p.chain_code = %s
              AND pr.product_name IS NOT NULL
        """

        candidates: list[tuple[str, str]] = []
        try:
            with _pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (source_chain_code,))
                    candidates = [(barcode, name) for barcode, name in cur.fetchall()]
        except Exception as e:
            logger.error("Error resolving barcodes by names: %s", e)
            raise

        resolved: Dict[str, str] = {}
        for item_id, cart_name in item_names.items():
            matches = [
                (barcode, db_name, _name_match_score(cart_name, db_name))
                for barcode, db_name in candidates
            ]
            matches = [match for match in matches if match[2] >= 0.75]
            matches.sort(key=lambda match: match[2], reverse=True)

            if not matches:
                continue
            if len(matches) > 1 and matches[0][2] == matches[1][2]:
                logger.info("Ambiguous name fallback for cart item id %s", item_id)
                continue

            resolved[item_id] = matches[0][0]

        return resolved

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
        self,
        source_chain_code: str,
        barcodes: List[str],
        chain_codes: List[str] | None = None,
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

        chain_filter = "AND p.chain_code = ANY(%s)" if chain_codes is not None else ""
        query = f"""
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
              {chain_filter}
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
                    params: tuple[Any, ...] = (source_chain_code, barcodes)
                    if chain_codes is not None:
                        params = (source_chain_code, barcodes, chain_codes)
                    cur.execute(query, params)
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
