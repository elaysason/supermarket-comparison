# import xml.etree.ElementTree as ET
import gzip
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

import requests
from lxml import etree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.models import PriceModel, ProductModel, StoreModel
from app.scrapers.base import BaseScraper, FileType

logger = logging.getLogger(__name__)

# Module-level tag mapping based on file path patterns
TAG_MAPPING = {
    "price": {"Item", "Product"},
    "store": {"Store"},
    "promo": {"Promotion"},
}


def findtext_multi(elem, *tags, default=None):
    """Try multiple tag names, return first match found."""
    for tag in tags:
        result = elem.findtext(tag)
        if result is not None:
            return result
    return default


def parse_xml_date(date_str: str) -> datetime:
    """Parse dates like '2024/07/14 10:07' to datetime."""
    if not date_str:
        return datetime.now()  # or return None
    # Replace / with - for Python's datetime parser
    date_str = date_str.replace("/", "-")
    return datetime.strptime(date_str, "%Y-%m-%d %H:%M")


def _get_valid_tags(file_path: str) -> Set[str]:
    """Determine valid XML tags based on file path patterns."""
    path_lower = file_path.lower()

    for keyword, tags in TAG_MAPPING.items():
        if keyword in path_lower:
            return tags

    return set()  # Default empty set


class CommonXMLScraper(BaseScraper):
    def __init__(
        self,
        chain_name: str,
        chain_code: str,
        base_url: str,
        default_store_id: Optional[str] = None,
    ):
        self._chain_name = chain_name
        self._chain_code = chain_code
        self._base_url = base_url
        self._online_store_id: Optional[str] = default_store_id
        self._cached_file_url: Optional[str] = None
        self._session = self._create_session()

    @staticmethod
    def _create_session(verify: bool = True) -> requests.Session:
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
        session.verify = verify
        return session

    @property
    def chain_name(self) -> str:
        return self._chain_name

    @property
    def online_store(self) -> str:
        return self._online_store_id

    @property
    def chain_code(self) -> str:
        return self._chain_code

    def parse(self, file_path):
        logger.info("Starting parse for %s", file_path)

        context = ET.iterparse(file_path, events=("end",))
        VALID_TAGS = _get_valid_tags(file_path)

        if not VALID_TAGS:
            logger.warning("No valid tags found for file path: %s", file_path)
            return

        items_found = 0

        try:
            for event, elem in context:
                try:
                    if elem.tag in VALID_TAGS:
                        processed_item = self._process_single_item(elem)
                        if processed_item:
                            items_found += 1
                            yield processed_item

                except Exception as e:
                    logger.error("Error processing element %s: %s", elem.tag, e)
                    continue

        except ET.ParseError:
            logger.error("XML Parse Error in %s", file_path, exc_info=True)

    def _process_single_item(self, elem: ET.Element) -> Optional[Dict[str, Any]]:
        """
        Takes a single XML element, extracts the required fields,
        and builds Pydantic Product and Price objects.
        """
        try:
            product_data = {
                "barcode": findtext_multi(elem, "ItemCode"),
                "product_name": findtext_multi(elem, "ItemName"),
                "unit_name": findtext_multi(elem, "UnitMeasure", "UnitOfMeasure"),
                "total_quantity": float(findtext_multi(elem, "Quantity", default="0")),
                "manufacturer_name": findtext_multi(
                    elem, "ManufactureName", "ManufacturerName"
                ),
            }
            price_data = {
                "chain_code": self._chain_code,
                "store_code": self._online_store_id,
                "barcode": product_data["barcode"],
                "price": float(findtext_multi(elem, "Price", "ItemPrice")),
                "update_date": parse_xml_date(findtext_multi(elem, "PriceUpdateDate")),
            }
            product_model = ProductModel(**product_data)
            # Used price model calc and unit name for PPU calculation, but not saved to DB
            price_data["calc_quantity"] = product_model.total_quantity
            price_data["calc_unit_name"] = product_model.unit_name

            price_model = PriceModel(**price_data)
            return {"product": product_model, "price": price_model}

        except Exception as e:
            logger.error("Error processing item: %s", e)
            return None

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        pass

    def find_online_store(
        self, stores_file: str, store_type: str = "2"
    ) -> Optional[StoreModel]:
        """Parse a stores XML and return the first store
        matching the given StoreType."""
        try:
            context = ET.iterparse(stores_file, events=("end",))
            for _, elem in context:
                if elem.tag in ("Store", "STORE"):
                    stype = findtext_multi(elem, "STORETYPE", "StoreType", default="")
                    if stype.strip() == store_type:
                        store_id = findtext_multi(elem, "STOREID", "StoreId")
                        if store_id:
                            self._online_store_id = store_id.strip()
                            store_name = findtext_multi(elem, "STORENAME", "StoreName")
                            logger.info("Found online store: %s", store_id.strip())
                            return StoreModel(
                                chain_code=self._chain_code,
                                store_code=self._online_store_id,
                                store_name=store_name,
                            )
        except Exception as e:
            logger.error("Error parsing stores file: %s", e)
        return None

    def download_file(self, file_path: str) -> bool:
        """Downloads and decompresses a gzipped file from the cached URL."""
        if not self._cached_file_url:
            logger.warning("No URL available to download")
            return False

        try:
            response = self._session.get(
                self._cached_file_url, stream=True, timeout=120
            )
            response.raise_for_status()

            gz_path = f"{file_path}.gz"
            with open(gz_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            with gzip.open(gz_path, "rb") as f_in:
                with open(file_path, "wb") as f_out:
                    while True:
                        chunk = f_in.read(8192)
                        if not chunk:
                            break
                        f_out.write(chunk)

            os.remove(gz_path)
            logger.info("Downloaded and extracted to %s", file_path)
            return True

        except requests.RequestException as e:
            logger.error("Download error: %s", e)
            return False
        except Exception as e:
            logger.error("Error processing file: %s", e)
            return False

    def download_latest(
        self,
        file_type: FileType = FileType.PRICE_FULL,
        base_dir: str = "chains_downloads",
    ) -> Optional[str]:
        """Download the latest price file into the chain folder."""
        safe_chain_name = self.chain_name.lower().replace(" ", "_")
        target_dir = os.path.join(base_dir, safe_chain_name)
        Path(target_dir).mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix_map = {
            FileType.PRICE_FULL: "pricefull",
            FileType.PRICE_DELETA: "price",
            FileType.STORES: "stores",
        }
        prefix = prefix_map.get(file_type, file_type.value.lower())
        output_path = os.path.join(target_dir, f"{prefix}_{timestamp}.xml")

        url = self.get_latest_file_url(file_type)
        if url:
            self._cached_file_url = url
            if self.download_file(output_path):
                return output_path

        return None
