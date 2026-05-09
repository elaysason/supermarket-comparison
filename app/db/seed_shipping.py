"""
Create and seed the shipping_costs table.

Run once (and re-run whenever fees change):
    uv run python -m app.db.seed_shipping

Schema
------
shipping_costs (
    chain_code      TEXT        references chains(chain_code),
    option_type     TEXT        'delivery' | 'pickup',
    fee             NUMERIC     base fee in NIS
    free_above      NUMERIC     cart total above which fee = 0  (NULL = never free)
    min_order       NUMERIC     minimum cart total to use this option (NULL = no min)
    notes           TEXT        human-readable description
    updated_at      TIMESTAMPTZ
    PRIMARY KEY (chain_code, option_type)
)
"""

import logging
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS shipping_costs (
    chain_code  TEXT        NOT NULL REFERENCES chains(chain_code),
    option_type TEXT        NOT NULL CHECK (option_type IN ('delivery', 'pickup')),
    fee         NUMERIC     NOT NULL,
    free_above  NUMERIC,
    min_order   NUMERIC,
    notes       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chain_code, option_type)
);
"""

# Each tuple: (chain_code, option_type, fee, free_above, min_order, notes)
SEED_DATA = [
    # Shufersal — delivery flat ₪30, no free threshold
    (
        "7290027600007",
        "delivery",
        30.0,
        None,
        None,
        "משלוח עד הבית ₪30",
    ),
    # Shufersal — pickup ₪15 under ₪750, ₪10 at ₪750+
    # We store the lower tier fee; the backend picks the right one based on cart total.
    # free_above=None because it never drops to zero, just to ₪10.
    # We encode the ₪750 threshold in notes and handle the two-tier logic in code.
    (
        "7290027600007",
        "pickup",
        15.0,
        None,
        None,
        "איסוף עצמי ₪15 (מתחת ₪750) / ₪10 (₪750+)",
    ),
    # Rami Levi — delivery ₪35.9, no pickup, no free threshold
    (
        "7290058140886",
        "delivery",
        35.9,
        None,
        None,
        "משלוח עד הבית ₪35.9",
    ),
    # Yohananof — pickup only, ₪15 under ₪1000, free at ₪1000+, min order ₪250
    (
        "7290803800003",
        "pickup",
        15.0,
        1000.0,
        250.0,
        "איסוף עצמי ₪15 (עד ₪1000) / חינם (₪1000+), מינימום הזמנה ₪250",
    ),
    # Hazi Hinam — delivery ₪29, min order ₪500
    (
        "7290700100008",
        "delivery",
        29.0,
        None,
        500.0,
        "משלוח עד הבית ₪29, מינימום הזמנה ₪500",
    ),
]

UPSERT = """
INSERT INTO shipping_costs
    (chain_code, option_type, fee, free_above, min_order, notes, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (chain_code, option_type) DO UPDATE SET
    fee        = EXCLUDED.fee,
    free_above = EXCLUDED.free_above,
    min_order  = EXCLUDED.min_order,
    notes      = EXCLUDED.notes,
    updated_at = NOW();
"""


def main():
    conn_args = dict(
        user=os.getenv("user"),
        password=os.getenv("password"),
        host=os.getenv("host"),
        port=os.getenv("port"),
        dbname=os.getenv("dbname"),
    )
    with psycopg.connect(**conn_args) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            logger.info("Table shipping_costs ready.")
            for row in SEED_DATA:
                cur.execute(UPSERT, row)
                logger.info("Upserted %s / %s", row[0], row[1])
        conn.commit()
    logger.info("Done.")


if __name__ == "__main__":
    main()
