import gzip
import html
import os
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.scrapers.base import FileType
from app.scrapers.common import CommonXMLScraper


class ShufersalCategory(IntEnum):
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
            chain_code="7290055746677",  # Shufersal's chain code
            online_store_id="413",
        )
        self._cached_file_url: Optional[str] = None
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        """
        Fetches the latest file URL using the Shufersal background API.
        """
        if file_type != FileType.PRICE_FULL:
            return None

        if self._cached_file_url:
            return self._cached_file_url

        try:
            url = f"{self.BASE_URL}{self.UPDATE_CATEGORY_ENDPOINT}"
            query_params = {
                "catId": ShufersalCategory.PRICES_FULL.value,
                "storeId": self.online_store,
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

    def download_file(self, file_path: str, use_cache: bool = True) -> bool:
        """
        Downloads the latest price file from Shufersal.

        Args:
            file_path: Path where the file should be saved (without .gz extension)
            use_cache: If True, use cached URL; otherwise fetch new URL

        Returns:
            True if download succeeded, False otherwise
        """
        url = (
            self._cached_file_url
            if use_cache
            else self.get_latest_file_url(FileType.PRICE_FULL)
        )

        if not url:
            print("No URL available to download")
            return False

        try:
            response = requests.get(url, stream=True, timeout=120)
            response.raise_for_status()

            # Save as gzipped file
            gz_path = f"{file_path}.gz"
            with open(gz_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Decompress to final path
            with gzip.open(gz_path, "rb") as f_in:
                with open(file_path, "wb") as f_out:
                    # Read in chunks to handle large files
                    while True:
                        chunk = f_in.read(8192)
                        if not chunk:
                            break
                        f_out.write(chunk)

            # Remove the gz file after extraction
            os.remove(gz_path)

            print(f"Downloaded and extracted to {file_path}")
            return True

        except requests.RequestException as e:
            print(f"Download error: {e}")
            return False
        except Exception as e:
            print(f"Error processing file: {e}")
            return False

    def download_latest(self, base_dir: str = "chains_downloads") -> Optional[str]:
        """
        Convenience method to download the latest price file into the chain-specific folder.
        """
        # Format "Shufersal" -> "shufersal", or "Rami Levy" -> "rami_levy" to match your folders
        safe_chain_name = self.chain_name.lower().replace(" ", "_")
        target_dir = os.path.join(base_dir, safe_chain_name)

        # Ensure the chains_downloads/shufersal directory actually exists
        Path(target_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename (e.g., pricefull_20260314_173000.xml)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(target_dir, f"pricefull_{timestamp}.xml")

        # 1. Fetch the URL via the background API
        self.get_latest_file_url(FileType.PRICE_FULL)

        # 2. Stream, unzip, and save directly to chains_downloads/shufersal/...
        if self.download_file(output_path):
            return output_path

        return None
