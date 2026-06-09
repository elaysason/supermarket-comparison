import logging
from typing import Optional

from app.scrapers.base import FileType, PriceUpdateStrategy
from app.scrapers.common import CommonXMLScraper
from bs4 import BeautifulSoup
from datetime import date

logger = logging.getLogger(__name__)


class HaziHinamCategory:
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
        self._category_mapping = {
            FileType.PRICE_FULL: HaziHinamCategory.PRICES,
            FileType.STORES: HaziHinamCategory.STORES,
        }
        self._session = self._create_session(verify=False)

    @property
    def price_update_strategy(self) -> PriceUpdateStrategy:
        # Hazi Hinam's portal exposes only full price files (no delta endpoint).
        return PriceUpdateStrategy.FULL_ONLY

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        category = self._file_type_to_category(file_type)
        if category is None:
            return None

        logger.info("Fetching latest %s file URL...", file_type.value)

        params = {
            "s": "null" if file_type == FileType.STORES else self._online_store_id,
            "d": date.today().isoformat(),
            "t": category,
            "f": "null" if file_type == FileType.STORES else "full",
        }

        file_page = self._session.get(self._base_url, params=params, timeout=10)
        soup = BeautifulSoup(file_page.text, "html.parser")
        table = soup.find("table", class_="table-striped")
        if not table:
            logger.warning("No table found on page for %s", file_type.value)
            return None

        all_rows = table.find_all("tr")
        headers = [el.text.strip() for el in all_rows[0].find_all(["th", "td"])]
        for row in all_rows[1:]:
            cells = [el.text.strip() for el in row.find_all("td")]
            if cells:
                row_dict = dict(zip(headers, cells))
                if (
                    file_type == FileType.STORES
                    or row_dict.get("קוד חנות") == self._online_store_id
                ):
                    file_name = row_dict.get("קובץ")
                    if file_name:
                        url = self.base_download_url + file_name
                        logger.info("Found latest %s URL: %s", file_type.value, url)
                        return url

        logger.warning("No %s files found", file_type.value)
        return None
