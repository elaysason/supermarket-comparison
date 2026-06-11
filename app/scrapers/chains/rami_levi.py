import logging
from typing import Optional

from bs4 import BeautifulSoup

from app.scrapers.base import FileType
from app.scrapers.common import CommonXMLScraper

logger = logging.getLogger(__name__)


class RamiLeviScraper(CommonXMLScraper):
    """Rami Levi supermarket scraper implementation."""

    LOGIN = "/login"
    LOGIN_POST = "/login/user"
    USERNAME = "RamiLevi"

    def __init__(self):
        super().__init__(
            chain_name="Rami Levi",
            chain_code="7290058140886",
            base_url="https://url.retail.publishedprices.co.il",
            default_store_id="039",
        )
        self._session = self._create_session(verify=False)
        self._authenticated = False
        self._csrf_token: Optional[str] = None

    def _authenticate(self) -> bool:
        """Extracts the CSRF token and submits the POST login payload."""
        if self._authenticated:
            return True

        session = self._session
        login_post_url = f"{self._base_url}{self.LOGIN_POST}"
        logger.info("Fetching login page to extract CSRF token for '%s'", self.USERNAME)
        try:
            initial_response = session.get(f"{self._base_url}{self.LOGIN}", timeout=10)
            initial_response.raise_for_status()
        except Exception as e:
            logger.error("Could not reach the login page: %s", e)
            return False

        soup = BeautifulSoup(initial_response.text, "html.parser")

        csrf_meta = soup.find("meta", {"name": "csrftoken"}) or soup.find(
            "meta", {"name": "csrf-token"}
        )

        if not csrf_meta:
            logger.error("Could not locate 'csrftoken' in the meta tags.")
            return False

        self._csrf_token = csrf_meta.get("content", "")
        logger.info("CSRF Token acquired: %s...", self._csrf_token[:15])

        payload = {
            "r": "",
            "username": self.USERNAME,
            "password": "",
            "csrftoken": self._csrf_token,
        }

        logger.info("Submitting authentication payload...")
        login_response = session.post(login_post_url, data=payload, timeout=10)

        if "login" in login_response.url.lower():
            logger.error(
                "Login failed: server rejected credentials"
                " and kept us on the login page."
            )
            return False

        logger.info("Authentication successful. Session is unlocked.")
        self._authenticated = True
        return True

    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        """Fetches the latest file URL using the Rami Levi background API."""
        if not self._authenticate():
            logger.error("Authentication failed. Cannot fetch file URL.")
            return None

        logger.info("Fetching latest %s file URL...", file_type.value)

        file_page = self._session.get(f"{self._base_url}/file", timeout=10)
        soup2 = BeautifulSoup(file_page.text, "html.parser")
        csrf_meta2 = soup2.find("meta", {"name": "csrftoken"}) or soup2.find(
            "meta", {"name": "csrf-token"}
        )
        file_csrf = csrf_meta2.get("content", "") if csrf_meta2 else ""
        logger.debug("File page CSRF: %s...", file_csrf[:15])
        logger.debug("Cookies: %s", dict(self._session.cookies))

        search = f"{file_type.value}{self.chain_code}"
        if file_type == FileType.STORES:
            search += "-000-"
        elif self._online_store_id:
            # Stores files are chain-wide (branch 000); branch-specific files
            # must be scoped so we do not ingest another store.
            search += f"-{self._online_store_id}-"

        api_url = f"{self._base_url}/file/json/dir"
        api_data = {"sEcho": 1, "sSearch": search, "csrftoken": file_csrf}

        # 1. Get total count with minimal payload
        resp = self._session.post(
            api_url,
            data={**api_data, "iDisplayStart": 0, "iDisplayLength": 1},
            timeout=30,
        )
        result = resp.json()
        total = int(result.get("iTotalDisplayRecords", 0))
        if total == 0:
            if file_type != FileType.STORES:
                logger.warning(
                    "No %s files found for store %s.",
                    file_type.value,
                    self._online_store_id,
                )
            else:
                logger.warning("No %s files found.", file_type.value)
            return None

        # 2. Fetch last entry (server returns oldest-first, so last = newest)
        resp = self._session.post(
            api_url,
            data={
                **api_data,
                "sEcho": 2,
                "iDisplayStart": total - 1,
                "iDisplayLength": 1,
            },
            timeout=30,
        )
        result = resp.json()
        files = result.get("aaData", [])
        if not files:
            logger.warning("No %s files found.", file_type.value)
            return None

        entry = files[0]
        if isinstance(entry, dict):
            latest_filename = entry.get("fname") or entry.get("name")
        elif isinstance(entry, list):
            latest_filename = entry[0]
        else:
            latest_filename = entry
        download_url = f"{self._base_url}/file/d/{latest_filename}"
        logger.info("Found latest %s URL: %s", file_type.value, download_url)
        return download_url
