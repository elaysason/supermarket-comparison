from app.scrapers.base import BaseScraper
from app.scrapers.chains.carrefour import CarrefourScraper
from app.scrapers.chains.hazi_hinam import HaziHinamScraper
from app.scrapers.chains.rami_levi import RamiLeviScraper
from app.scrapers.chains.shufersal import ShufersalScraper
from app.scrapers.chains.yohananof import YohananofScraper


SCRAPER_CLASSES: tuple[type[BaseScraper], ...] = (
    CarrefourScraper,
    HaziHinamScraper,
    YohananofScraper,
    RamiLeviScraper,
    ShufersalScraper,
)


def get_scrapers() -> list[BaseScraper]:
    return [scraper_class() for scraper_class in SCRAPER_CLASSES]
