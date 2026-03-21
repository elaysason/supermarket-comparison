import html
from typing import Optional

from bs4 import BeautifulSoup

from app.scrapers.base import FileType
from app.scrapers.common import CommonXMLScraper


class ShufersalCategory:
    PRICES = 1
    PRICES_FULL = 2
    PROMOS = 3
    PROMOS_FULL = 4
    STORES = 5


class ShufersalScraper(CommonXMLScraper):
    """Shufersal supermarket scraper implementation."""

    BASE_URL = "https://prices.shufersal.co.il"
    UPDATE_CATEGORY_ENDPOINT = "/FileObject/UpdateCategory"

    def __init__(self):
        super().__init__(
            chain_name="Shufersal",
            chain_code="7290027600007",
        )

    def _file_type_to_category(self, file_type: FileType) -> Optional[int]:
        """Maps a FileType to the corresponding Shufersal API category."""
        mapping = {
            FileType.PRICE_FULL: ShufersalCategory.PRICES_FULL,
            FileType.PRICE_DELETA: ShufersalCategory.PRICES,
            FileType.STORES: ShufersalCategory.STORES,
        }
        return mapping.get(file_type)

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        """
        Fetches the latest file URL using the Shufersal background API.
        """
        category = self._file_type_to_category(file_type)
        if category is None:
            return None

        if self._cached_file_url:
            return self._cached_file_url

        try:
            url = f"{self.BASE_URL}{self.UPDATE_CATEGORY_ENDPOINT}"
            query_params = {
                "catId": category,
                "storeId": self.online_store or 0,
            }

            # 1. Fetch the HTML table via API
            response = self._session.get(url, params=query_params, timeout=60)
            response.raise_for_status()

            # 2. Parse the table to find the download link
            soup = BeautifulSoup(response.text, "html.parser")
            tag = soup.find("a", text="לחץ להורדה")

            if tag:
                raw_url = tag.get("href", "")
                clean_url = html.unescape(raw_url)
                self._cached_file_url = clean_url
                print(f"Successfully found URL: {clean_url}")
                return clean_url
            else:
                print("Could not find 'לחץ להורדה' link in the returned HTML.")

        except Exception as e:
            print(f"Error fetching Shufersal price URL via API: {e}")

        return None
