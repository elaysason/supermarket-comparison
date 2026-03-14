from app.scrapers.base import FileType
from app.scrapers.chains.shufersal import ShufersalScraper


def main():
    scraper = ShufersalScraper()
    latest_file_url = scraper.get_latest_file_url(FileType.PRICE_FULL)
    if latest_file_url:
        print(f"Latest file URL: {latest_file_url}")
        scraper.download_latest()
    else:
        print("No latest file URL found.")


if __name__ == "__main__":
    main()
