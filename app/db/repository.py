import os
from typing import Any, Generator, List

import psycopg
from dotenv import load_dotenv

from app.models import PriceModel

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

    def _chunk_data(
        self, data: List[Any], chunk_size: int = 1000
    ) -> Generator[List[Any], None, None]:
        """Yields chunks of the data array to prevent locking the database."""
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    def upsert_prices(self, store_id: int, prices: List[PriceModel]):
        """Executes a binary bulk UPSERT."""
        if not prices:
            print("No prices to insert. Skipping.")
            return

        upsert_query = """
            INSERT INTO prices (
                store_id, 
                barcode, 
                price, 
                price_per_unit,
                update_date
            ) 
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (store_id, barcode) DO UPDATE SET
                price = EXCLUDED.price,
                price_per_unit = EXCLUDED.price_per_unit,
                update_date = EXCLUDED.update_date;
        """

        try:
            with psycopg.connect(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                dbname=self.dbname,
            ) as conn:
                with conn.cursor() as cur:
                    for chunk in self._chunk_data(prices):
                        # Translate Pydantic models -> pure Python tuples
                        data_tuples = [
                            (
                                store_id,
                                p.barcode,
                                p.price,
                                p.price_per_unit,
                                p.price_update_date,
                            )
                            for p in chunk
                        ]

                        cur.executemany(upsert_query, data_tuples)

                # Commit the transaction only when ALL chunks succeed.
                conn.commit()
                print(
                    f"Successfully upserted {len(prices)} rows for Store ID {store_id}."
                )

        except Exception as e:
            print(f"Database insertion failed: {e}")
            raise
