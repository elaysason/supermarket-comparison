import json
import logging
import re
from datetime import date
from typing import List, Optional

from lxml import etree as ET

from app.models import StoreModel
from app.scrapers.base import FileType
from app.scrapers.common import CommonXMLScraper, findtext_multi

logger = logging.getLogger(__name__)


class CarrefourScraper(CommonXMLScraper):
    """Carrefour supermarket scraper implementation.

    The Carrefour pricing site (prices.carrefour.co.il) serves a single HTML
    page per date with the entire file list embedded as a JavaScript constant
    (``const files = [...]``).  Filtering by category and branch is done
    client-side in the browser; there is no separate API.

    This scraper replicates that client-side logic:
      1. Fetch the HTML for a given date.
      2. Extract the inline ``files`` JSON array.
      3. Filter by file-type (category) and store (branch) using filename
         patterns.
      4. Return the download URL for the most recently modified match.
    """

    # Regex to pull the JSON array out of  ``const files = [...]``
    _FILES_RE = re.compile(r"const\s+files\s*=\s*(\[.*?\])\s*;", re.DOTALL)

    _EXPECTED_STORE_ID = "5304"
    _EXPECTED_STORE_NAME_MARKER = "קרפור אונליין"

    def __init__(self):
        super().__init__(
            chain_name="Carrefour",
            chain_code="7290055700007",
            base_url="https://prices.carrefour.co.il",
            default_store_id=self._EXPECTED_STORE_ID,
        )

    def find_online_store(self, stores_file: str, store_type: str = "2"):
        """Find the main Carrefour online store from the Stores XML.

        Carrefour has multiple StoreType=2 entries (5204 "Quick", 5304 main
        online, 9032 Bitan).  The base implementation picks the first match
        (5204) which is a small subset (~1000 items).

        This override looks for store 5304 *and* verifies its name still
        contains "קרפור אונליין".  If the expected store disappears or is
        renamed, it falls back to the base class auto-discovery and logs a
        warning so the change is noticed.
        """
        try:
            context = ET.iterparse(stores_file, events=("end",))
            for _, elem in context:
                if elem.tag not in ("Store", "STORE"):
                    continue
                stype = findtext_multi(elem, "STORETYPE", "StoreType", default="").strip()
                if stype != store_type:
                    continue

                store_id = findtext_multi(elem, "STOREID", "StoreId", "StoreID", default="").strip()
                store_name = findtext_multi(elem, "STORENAME", "StoreName", default="").strip()

                if store_id == self._EXPECTED_STORE_ID and self._EXPECTED_STORE_NAME_MARKER in store_name:
                    self._online_store_id = store_id
                    logger.info(
                        "Found expected online store %s (%s)",
                        store_id,
                        store_name,
                    )
                    return StoreModel(
                        chain_code=self._chain_code,
                        store_code=store_id,
                        store_name=store_name,
                    )
        except Exception as e:
            logger.error("Error parsing Carrefour stores file: %s", e)

        logger.warning(
            "Expected Carrefour online store %s with name containing '%s' "
            "not found. Falling back to auto-discovery.",
            self._EXPECTED_STORE_ID,
            self._EXPECTED_STORE_NAME_MARKER,
        )
        return super().find_online_store(stores_file, store_type)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_file_list(self, target_date: Optional[str] = None) -> List[dict]:
        """Fetch the HTML page and extract the embedded ``files`` array.

        Args:
            target_date: Date string in ``YYYYMMDD`` format.  Defaults to
                today.

        Returns:
            A list of dicts, each with keys ``name``, ``size``, ``modified``.
        """
        if target_date is None:
            target_date = date.today().strftime("%Y%m%d")

        url = f"{self._base_url}/?date={target_date}"
        logger.info("Fetching Carrefour file listing from %s", url)

        response = self._session.get(url, timeout=60)
        response.raise_for_status()

        match = self._FILES_RE.search(response.text)
        if not match:
            logger.warning("Could not find 'const files' array in page HTML")
            return []

        try:
            files: list = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse files JSON: %s", exc)
            return []

        logger.info("Found %d files in Carrefour listing", len(files))
        return files

    @staticmethod
    def _extract_branch_code(filename: str) -> Optional[str]:
        """Extract the branch/store code from a Carrefour filename.

        Filename structures:
          - 3-part: ``PriceFull7290055700007-5304-202605210700.gz``
            → parts = [``PriceFull7290055700007``, ``5304``, ``202605210700.gz``]
            → branch is parts[1]
          - 5-part (newer): branch is parts[2]
        """
        parts = filename.split("-")
        if len(parts) == 3:
            return parts[1]
        elif len(parts) >= 5:
            return parts[2]
        return None

    @staticmethod
    def _matches_category(filename: str, file_type: FileType) -> bool:
        """Check if *filename* belongs to the given *file_type* category.

        Uses a word-boundary approach so that ``Price`` does not match
        ``PriceFull`` (mirrors the site's JS ``isCategoryFiltered``).
        """
        category = file_type.value  # e.g. "PriceFull", "Price", "Stores"
        # The site uses:  new RegExp(`\\b${category}(?![a-zA-Z])`)
        pattern = re.compile(rf"\b{re.escape(category)}(?![a-zA-Z])", re.IGNORECASE)
        return pattern.search(filename) is not None

    def _filter_files(
        self,
        files: List[dict],
        file_type: FileType,
        store_code: Optional[str] = None,
    ) -> List[dict]:
        """Filter the file list by category and optional branch code."""
        result = []
        for f in files:
            name: str = f.get("name", "")

            # Strip leading "NULL" prefix that some filenames have
            clean_name = name.lstrip("NULL") if name.startswith("NULL") else name

            if not self._matches_category(clean_name, file_type):
                continue

            if store_code is not None:
                branch = self._extract_branch_code(name)
                if branch is None:
                    continue
                # Compare as integers to handle zero-padding differences
                try:
                    if int(branch) != int(store_code):
                        continue
                except ValueError:
                    continue

            result.append(f)

        return result

    # ------------------------------------------------------------------
    # Public API  (overrides base)
    # ------------------------------------------------------------------

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        """Return the download URL for the latest file matching *file_type*
        and the configured store.

        The URL is constructed as::

            {base_url}/{YYYYMMDD}/{filename}
        """
        if self._cached_file_url:
            return self._cached_file_url

        logger.info("Fetching latest %s file URL for store %s...",
                     file_type.value, self._online_store_id)

        try:
            today = date.today().strftime("%Y%m%d")
            files = self._fetch_file_list(today)
            if not files:
                logger.warning("No files returned from Carrefour listing")
                return None

            # Stores files use branch code "000" (chain-wide), so don't
            # filter them by the individual store code.
            store_filter = None if file_type == FileType.STORES else self._online_store_id
            filtered = self._filter_files(
                files,
                file_type,
                store_code=store_filter,
            )

            if not filtered:
                logger.warning(
                    "No %s files found for store %s",
                    file_type.value,
                    self._online_store_id,
                )
                return None

            # Pick the first file (list is already sorted by modified date on
            # the server side, newest first).
            chosen = filtered[0]
            download_url = f"{self._base_url}/{today}/{chosen['name']}"

            self._cached_file_url = download_url
            logger.info("Found latest %s URL: %s", file_type.value, download_url)
            return download_url

        except Exception as e:
            logger.error("Error fetching %s file URL: %s", file_type.value, e)

        return None
