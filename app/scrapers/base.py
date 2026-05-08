from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Generator, Optional


class FileType(Enum):
    PRICE_FULL = "PriceFull"
    PRICE_DELTA = "Price"
    PROMO = "PromoFull"
    PROMO_DELTA = "Promo"
    STORES = "Stores"


class PriceUpdateStrategy(str, Enum):
    FULL_ONLY = "full_only"
    DELTA_WITH_FULL_FALLBACK = "delta_with_full_fallback"


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

    @property
    def price_update_strategy(self) -> PriceUpdateStrategy:
        return PriceUpdateStrategy.DELTA_WITH_FULL_FALLBACK

    @property
    def item_tag_name(self) -> str:
        """Override this if the XML structure uses a different tag for items."""
        return "Product"

    @abstractmethod
    def get_latest_file_url(self, file_type: FileType) -> Optional[str]:
        """returns the latest file URL for the given file type.

        Args:
            file_type: Requested file type (PriceFull, PriceDelta, PromoFull, PromoDelta
            ,Stores)

        Returns:
            str: The latest file URL, or None if not found."""
        pass

    @abstractmethod
    def parse(self, file_path: str) -> Generator[Dict[str, Any], None, None]:
        """Parses the given file and yields product data as dictionaries."""
        pass
