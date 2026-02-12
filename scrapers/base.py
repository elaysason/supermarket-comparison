from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Generator, Optional


class FileType(Enum):
    PRICE_FULL = "PriceFull"
    PRICE_DELETA = "Price"
    PROMO = "PromoFull"
    PROMO_DELETA = "Promo"


class BaseScraper(ABC):
    """Abstract base class for supermarket scrapers."""

    @property
    @abstractmethod
    def chain_name(self) -> str:
        pass

    @property
    @abstractmethod
    def online_store(self) -> str:
        pass

    @property
    @abstractmethod
    def chain_code(self) -> str:
        pass

    def get_latest_file_url(selfself, file_type: FileType) -> Optional[str]:
        pass

    @abstractmethod
    def parse(self, file_path: str) -> Generator[Dict[str, Any], None, None]:
        pass
