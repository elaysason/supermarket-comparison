from abc import ABC, abstractmethod
from typing import List


class BaseScraper(ABC):
    """Abstract base class for supermarket scrapers."""

    @property
    @abstractmethod
    def chain_name(self) -> str:
        pass

    @abstractmethod
    def online_store(self) -> str:
        pass
