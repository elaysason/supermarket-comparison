import logging

from app.scrapers.common import CommonXMLScraper

logger = logging.getLogger(__name__)


class ShufersalCategory:
    PRICES = 1
    DEALS = 2
    STORES = 3


class HaziHinamScraper(CommonXMLScraper):
    """Hazi Hinam supermarket scraper implementation."""

    def __init__(self):
        super().__init__(
            chain_name="Hazi Hinam",
            chain_code="7290700100008",
            base_url="https://shop.hazi-hinam.co.il/Prices",
            default_store_id="103",
        )
        self.base_download_url = (
            "https://hazihinamprod01.blob.core.windows.net/regulatories/"
        )
