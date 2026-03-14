# import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, Optional, Set

from lxml import etree as ET

from app.models import PriceModel, ProductModel
from app.scrapers.base import BaseScraper, FileType

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
    def __init__(self, chain_name: str, chain_code: str, online_store_id: str):
        self._chain_name = chain_name
        self._chain_code = chain_code
        self._online_store_id = online_store_id

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
        print(f"Starting parse for {file_path}...")

        context = ET.iterparse(file_path, events=("end",))
        VALID_TAGS = _get_valid_tags(file_path)

        if not VALID_TAGS:
            print(f"Warning: No valid tags found for file path: {file_path}")
            return

        items_found = 0

        try:
            for event, elem in context:
                if elem.tag in VALID_TAGS:
                    processed_item = self._process_single_item(elem)
                    if processed_item:
                        items_found += 1
                        yield processed_item

                    elem.clear()
                    parent = elem.getparent()
                    if parent is not None:
                        parent.remove(elem)

        except ET.ParseError as e:
            # logger.error כולל exc_info=True ידפיס גם את ה-Stack Trace!
            print(f"XML Parse Error in {file_path}: {e}")

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
            }
            price_data = {
                "store_id": int(findtext_multi(elem, "StoreID", default="0")),
                "barcode": product_data["barcode"],
                "price": float(findtext_multi(elem, "Price", "ItemPrice")),
                "price_update_date": parse_xml_date(
                    findtext_multi(elem, "PriceUpdateDate")
                ),
            }
            product_model = ProductModel(**product_data)
            # Used price model calc and unit name for PPU calculation, but not saved to DB
            price_data["calc_quantity"] = product_model.total_quantity
            price_data["calc_unit_name"] = product_model.unit_name

            price_model = PriceModel(**price_data)
            return {"product": product_model, "price": price_model}

        except Exception as e:
            print(f"Error processing item: {e}")
            return None

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        pass
